let publicRoles = [];
let publicProgressTimer = null;

document.getElementById("publicChatForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const questionInput = document.getElementById("publicQuestion");
  const question = questionInput.value.trim();
  if (!question) {
    return;
  }

  if (question.toLowerCase() === "/clear") {
    questionInput.value = "";
    resetPublicChat();
    return;
  }

  const selectedRole = getSelectedPublicRole();
  appendPublicMessage("user", "User", question);
  questionInput.value = "";
  const pendingMessage = appendPublicMessage("assistant running pending", "Assistant", "요청을 전송하고 있습니다.", {
    status: "RUNNING",
    role: selectedRole.role_id,
    clearance: selectedRole.default_clearance
  });
  startPublicProgress(pendingMessage);
  renderPublicSources({});

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        endpoint: "/api/answer",
        query: question,
        role_id: selectedRole.role_id,
        rbac_enabled: true,
        pre_check_enabled: true,
        post_check_enabled: true
      })
    });

    const data = await parseJsonResponse(response);
    if (!response.ok) {
      throw new Error(data.detail || data.message || `HTTP ${response.status}`);
    }

    const identity = data.effective_identity || {
      role_id: selectedRole.role_id,
      department_name: selectedRole.department,
      security_clearance: selectedRole.default_clearance
    };
    updatePublicIdentity(identity);

    const resultKind = getResultKind(data);
    stopPublicProgress();
    setPublicGuard(resultKind.status, resultKind.kind !== "success");
    setPublicProgress(resultKind.kind === "success" ? "답변이 완료되었습니다." : "처리가 완료되었습니다.");

    if (resultKind.kind === "blocked") {
      removePendingMessage(pendingMessage);
      appendBlockingMessage(data);
    } else if (resultKind.kind === "error") {
      removePendingMessage(pendingMessage);
      appendErrorMessage(data);
    } else {
      removePendingMessage(pendingMessage);
      appendPublicMessage("assistant markdown", "Assistant", data.answer || "", {
        status: resultKind.status,
        role: data.role_id || identity.role_id,
        clearance: data.security_clearance || identity.security_clearance
      });
    }

    renderPublicSources(data.sources || {});
  } catch (error) {
    removePendingMessage(pendingMessage);
    stopPublicProgress();
    setPublicGuard("ERROR", true);
    setPublicProgress("오류가 발생했습니다. 관리자 로그를 확인해 주세요.");
    appendErrorMessage({
      answer: `요청 처리 중 오류가 발생했습니다: ${error.message}`,
      role_id: getSelectedPublicRole().role_id,
      checks: {pre_check: "ERROR", post_check: "ERROR"}
    });
    renderPublicSources({});
  }
});

document.getElementById("publicRoleSelect").addEventListener("change", () => {
  const selectedRole = getSelectedPublicRole();
  updatePublicIdentity({
    role_id: selectedRole.role_id,
    department_name: selectedRole.department,
    security_clearance: selectedRole.default_clearance
  });
  setPublicGuard("READY", false);
  setPublicProgress("질문을 입력하면 처리 상태가 표시됩니다.");
  renderPublicSources({});
});

document.getElementById("newPublicChat").addEventListener("click", () => {
  document.getElementById("publicQuestion").value = "";
  resetPublicChat();
});

async function parseJsonResponse(response) {
  const responseText = await response.text();
  try {
    return responseText ? JSON.parse(responseText) : {};
  } catch {
    throw new Error(responseText || "Invalid JSON response");
  }
}

async function loadPublicRoles() {
  const response = await fetch("/api/admin/roles");
  publicRoles = await response.json();
  const roleSelect = document.getElementById("publicRoleSelect");
  roleSelect.innerHTML = publicRoles.map((role) => `
    <option value="${escapeHtml(role.role_id)}">${escapeHtml(role.role_id)}</option>
  `).join("");

  if (publicRoles.some((role) => role.role_id === "GENERAL_EMPLOYEE")) {
    roleSelect.value = "GENERAL_EMPLOYEE";
  }

  const selectedRole = getSelectedPublicRole();
  updatePublicIdentity({
    role_id: selectedRole.role_id,
    department_name: selectedRole.department,
    security_clearance: selectedRole.default_clearance
  });
  resetPublicChat();
}

function getSelectedPublicRole() {
  const roleId = document.getElementById("publicRoleSelect").value || "GENERAL_EMPLOYEE";
  return publicRoles.find((role) => role.role_id === roleId) || {
    role_id: roleId,
    role_name: roleId,
    department: "General",
    default_clearance: "INTERNAL"
  };
}

function updatePublicIdentity(identity) {
  const roleId = identity.role_id || "-";
  const department = identity.department_name || identity.department || "-";
  const clearance = identity.security_clearance || identity.default_clearance || "-";
  document.getElementById("publicRole").textContent = roleId;
  document.getElementById("publicDepartment").textContent = department;
  document.getElementById("publicClearance").textContent = clearance;
  document.getElementById("publicProfile").textContent = `${roleId} / ${clearance}`;
}

function resetPublicChat() {
  stopPublicProgress();
  const selectedRole = getSelectedPublicRole();
  document.getElementById("publicMessages").innerHTML = `
    <div class="chat-message assistant">
      <span>Assistant</span>
      <p>궁금한 내용을 입력해 주세요. 선택한 Role에 맞춰 답변을 준비합니다.</p>
    </div>
  `;
  updatePublicIdentity({
    role_id: selectedRole.role_id,
    department_name: selectedRole.department,
    security_clearance: selectedRole.default_clearance
  });
  setPublicGuard("READY", false);
  setPublicProgress("질문을 입력하면 처리 상태가 표시됩니다.");
  renderPublicSources({});
}

function renderPublicSources(sources) {
  const target = document.getElementById("publicCitations");
  if (!target) {
    return;
  }
  const tables = Array.isArray(sources.tables) ? sources.tables : [];
  const documents = Array.isArray(sources.documents) ? sources.documents : [];
  target.innerHTML = renderSourceSections(tables, documents);
}

function renderSourceSections(tables, documents) {
  const sections = [];
  if (tables.length) {
    sections.push(`
      <div class="source-section">
        <strong>조회 table</strong>
        ${tables.map((table) => `<div>${escapeHtml(table)}</div>`).join("")}
      </div>
    `);
  }
  if (documents.length) {
    sections.push(`
      <div class="source-section">
        <strong>문서 citation</strong>
        ${documents.map((doc) => `<div>${formatDocument(doc)}</div>`).join("")}
      </div>
    `);
  }
  return sections.length ? sections.join("") : '<span class="muted-empty">반환된 출처 없음</span>';
}

function getResultKind(data) {
  const guardStatus = String(data.guard_status || "").toUpperCase();
  const preCheck = String(data.checks?.pre_check || "").toUpperCase();
  const postCheck = String(data.checks?.post_check || "").toUpperCase();
  if (guardStatus === "ERROR" || preCheck === "ERROR" || postCheck === "ERROR") {
    return {kind: "error", status: "ERROR"};
  }
  if (Boolean(data.blocked)
    || ["BLOCKED", "DENIED"].includes(guardStatus)
    || preCheck === "BLOCKED"
    || postCheck === "BLOCKED") {
    return {kind: "blocked", status: "BLOCKED"};
  }
  return {kind: "success", status: guardStatus || "PASS"};
}

function setPublicGuard(status, blocked) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  document.getElementById("publicGuard").textContent = normalized;
  const guardCard = document.getElementById("publicGuard").closest(".guard-card");
  guardCard.classList.toggle("blocked", blocked);
  guardCard.classList.toggle("error", ["ERROR", "FAILED", "FAILURE"].includes(normalized));
  guardCard.classList.toggle("running", ["RUNNING", "PENDING", "WAITING"].includes(normalized));
}

function setPublicProgress(message) {
  const target = document.getElementById("publicProgress");
  if (target) {
    target.textContent = message;
  }
}

function startPublicProgress(pendingMessage = null) {
  stopPublicProgress();
  const steps = [
    {status: "RUNNING", message: "요청을 Databricks Job으로 전송 중입니다."},
    {status: "RUNNING", message: "선택한 Role 기준으로 권한을 확인 중입니다."},
    {status: "RUNNING", message: "관련 SQL과 근거 데이터를 검색 중입니다."},
    {status: "RUNNING", message: "검색 결과를 바탕으로 답변을 생성 중입니다."},
    {status: "RUNNING", message: "답변과 guard 결과를 정리 중입니다."}
  ];
  let index = 0;
  const renderStep = () => {
    const step = steps[Math.min(index, steps.length - 1)];
    setPublicGuard(step.status, false);
    setPublicProgress(step.message);
    updatePendingPublicMessage(pendingMessage, step.status, step.message);
    index += 1;
  };
  renderStep();
  publicProgressTimer = window.setInterval(renderStep, 4500);
}

function stopPublicProgress() {
  if (publicProgressTimer) {
    window.clearInterval(publicProgressTimer);
    publicProgressTimer = null;
  }
}

function appendBlockingMessage(data) {
  const checks = data.checks || {};
  const role = data.effective_identity?.role_id || data.role_id || "현재 사용자";
  const reason = data.answer || "현재 권한으로는 해당 질문에 관련된 데이터에 접근할 수 없습니다.";
  const detail = [
    `Role: ${role}`,
    `Pre-check: ${checks.pre_check || "UNKNOWN"}`,
    `Post-check: ${checks.post_check || "UNKNOWN"}`
  ].join(" · ");

  const message = document.createElement("div");
  message.className = "chat-message assistant blocked";
  message.innerHTML = `
    <div class="message-meta">
      <span>Access blocked</span>
      <strong class="status-pill blocked">BLOCKED</strong>
    </div>
    <div class="blocking-message">
      <strong>권한 확인 결과, 답변이 차단되었습니다.</strong>
      <p>${escapeHtml(reason)}</p>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
  appendMessageElement(message);
}

function appendErrorMessage(data) {
  const checks = data.checks || {};
  const role = data.effective_identity?.role_id || data.role_id || "현재 사용자";
  const reason = data.answer || "답변 생성 중 오류가 발생했습니다.";
  const detail = [
    `Role: ${role}`,
    `Pre-check: ${checks.pre_check || "ERROR"}`,
    `Post-check: ${checks.post_check || "ERROR"}`
  ].join(" · ");

  const message = document.createElement("div");
  message.className = "chat-message assistant error";
  message.innerHTML = `
    <div class="message-meta">
      <span>System error</span>
      <strong class="status-pill error">ERROR</strong>
    </div>
    <div class="blocking-message">
      <strong>실행 오류로 답변을 가져오지 못했습니다.</strong>
      <p>${escapeHtml(reason)}</p>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
  appendMessageElement(message);
}

function appendPublicMessage(type, label, text, meta = null) {
  const message = document.createElement("div");
  message.className = `chat-message ${type}`;
  const body = type.includes("markdown")
    ? `<div class="answer-body">${renderAnswer(text)}</div>`
    : `<p>${escapeHtml(text)}</p>`;
  const metaHtml = meta
    ? `
      <div class="message-meta">
        <span>${escapeHtml(label)}</span>
        <strong class="status-pill ${getStatusPillClass(meta.status)}">${escapeHtml(meta.status || "PASS")}</strong>
        <small>${escapeHtml([meta.role, meta.clearance].filter(Boolean).join(" / "))}</small>
      </div>
    `
    : `<span>${escapeHtml(label)}</span>`;
  message.innerHTML = `${metaHtml}${body}`;
  appendMessageElement(message);
  return message;
}

function appendMessageElement(message) {
  const messages = document.getElementById("publicMessages");
  messages.appendChild(message);
  scrollPublicMessagesToBottom();
  window.requestAnimationFrame(scrollPublicMessagesToBottom);
}

function scrollPublicMessagesToBottom() {
  const messages = document.getElementById("publicMessages");
  if (!messages) {
    return;
  }
  messages.scrollTop = messages.scrollHeight;
}

function removePendingMessage(message) {
  if (message && message.parentElement) {
    message.remove();
  }
}

function updatePendingPublicMessage(message, status, text) {
  if (!message || !message.parentElement) {
    return;
  }

  const statusTarget = message.querySelector(".status-pill");
  if (statusTarget) {
    statusTarget.textContent = status;
    statusTarget.className = `status-pill ${getStatusPillClass(status)}`;
  }

  const textTarget = message.querySelector("p");
  if (textTarget) {
    textTarget.textContent = text;
  }
  scrollPublicMessagesToBottom();
}

function getStatusPillClass(status) {
  const normalized = String(status || "").toUpperCase();
  if (["BLOCKED", "DENIED"].includes(normalized)) {
    return "blocked";
  }
  if (["ERROR", "FAILED", "FAILURE"].includes(normalized)) {
    return "error";
  }
  if (["RUNNING", "PENDING", "WAITING"].includes(normalized)) {
    return "running";
  }
  return "success";
}

function renderAnswer(value) {
  const lines = String(value).split(/\r?\n/);
  const html = [];
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${formatInline(paragraph.join("\n"))}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();

    if (!line || line === "---") {
      flushParagraph();
      continue;
    }

    if (isMarkdownTableStart(lines, index)) {
      flushParagraph();
      const tableLines = [];
      while (index < lines.length && isMarkdownTableLine(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      index -= 1;
      html.push(renderMarkdownTable(tableLines));
      continue;
    }

    if (line.startsWith("### ")) {
      flushParagraph();
      html.push(`<h4>${formatInline(line.slice(4).replace(/:$/, ""))}</h4>`);
      continue;
    }

    if (line.startsWith("> ")) {
      flushParagraph();
      html.push(`<blockquote>${formatInline(line.slice(2))}</blockquote>`);
      continue;
    }

    if (line.startsWith("- ")) {
      flushParagraph();
      const items = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(`<li>${formatInline(lines[index].trim().slice(2))}</li>`);
        index += 1;
      }
      index -= 1;
      html.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return html.join("");
}

function isMarkdownTableLine(line) {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|");
}

function isMarkdownTableStart(lines, index) {
  return isMarkdownTableLine(lines[index] || "") && isMarkdownTableLine(lines[index + 1] || "");
}

function renderMarkdownTable(tableLines) {
  const rows = tableLines
    .filter((line) => !/^\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|$/.test(line.trim()))
    .map((line) => line.trim().slice(1, -1).split("|").map((cell) => cell.trim()));

  if (!rows.length) {
    return "";
  }

  const columnCount = Math.max(...rows.map((row) => row.length));
  const headers = normalizeTableRow(rows[0], columnCount).map((cell, index) => {
    if (cell) {
      return cell;
    }
    return `항목 ${index + 1}`;
  });
  const bodyRows = rows.slice(1).map((row) => normalizeTableRow(row, columnCount));
  return `
    <div class="answer-table-wrap">
      <table class="answer-table">
        <thead><tr>${headers.map((cell) => `<th>${formatInline(cell)}</th>`).join("")}</tr></thead>
        <tbody>
          ${bodyRows.map((row) => `<tr>${row.map((cell) => `<td>${formatInline(cell)}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function normalizeTableRow(row, columnCount) {
  const normalized = [...row];
  while (normalized.length < columnCount) {
    normalized.push("");
  }
  return normalized.slice(0, columnCount);
}

function formatDocument(doc) {
  if (typeof doc === "string") {
    return escapeHtml(doc);
  }
  const parts = [doc.document_id, doc.chunk_id, doc.classification].filter(Boolean);
  return escapeHtml(parts.join(" / "));
}

function formatInline(value) {
  return escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadPublicRoles();

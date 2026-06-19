const titles = {
  overview: "Overview",
  adminDisplay: "Admin Sources",
  dashboard: "Dashboards",
  sqlLogs: "SQL Logs",
  simulator: "Admin Chat"
};

let lastResponse = null;
let sqlLogs = [];
let sqlLogPage = 1;
let sqlLogTotalPages = 1;
let expandedSqlLogIndex = null;
let roles = [];
let adminProgressTimer = null;

const sideNav = document.querySelector(".side-nav");
if (sideNav) {
  sideNav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-target]");
    if (!button || !sideNav.contains(button)) {
      return;
    }
    showView(button.dataset.target, button);
  });
}

document.getElementById("simulateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  simulate();
});

document.getElementById("role").addEventListener("change", (event) => {
  applyRoleDefaults(event.target.value);
});

["department", "clearance"].forEach((id) => {
  document.getElementById(id).addEventListener("change", syncProfile);
});

document.getElementById("refreshDashboard").addEventListener("click", loadDashboards);
document.getElementById("refreshSqlLogs").addEventListener("click", () => loadSqlLogs(sqlLogPage));
document.getElementById("applySqlLogFilters").addEventListener("click", () => loadSqlLogs(1));
document.getElementById("prevSqlLogPage").addEventListener("click", () => loadSqlLogs(Math.max(sqlLogPage - 1, 1)));
document.getElementById("nextSqlLogPage").addEventListener("click", () => loadSqlLogs(Math.min(sqlLogPage + 1, sqlLogTotalPages)));
document.getElementById("dashboardRole").addEventListener("change", (event) => {
  loadRoleAccess(event.target.value);
});
document.getElementById("logoutButton").addEventListener("click", () => {
  sessionStorage.removeItem("cosbelle_admin");
  window.location.href = "/admin-login";
});

function showView(id, button) {
  document.querySelectorAll(".view").forEach((section) => section.classList.remove("active"));
  document.querySelectorAll(".side-nav button").forEach((navButton) => navButton.classList.remove("active"));

  document.getElementById(id).classList.add("active");
  button.classList.add("active");
  document.getElementById("pageTitle").textContent = titles[id] || "Admin Console";

  if (id === "dashboard") {
    loadDashboards();
  }
  if (id === "adminDisplay") {
    renderAdminSources();
  }
  if (id === "sqlLogs") {
    loadSqlLogs(1);
  }
}

function setSelectValue(selectId, value) {
  const select = document.getElementById(selectId);
  const exists = Array.from(select.options).some((option) => option.value === value || option.textContent === value);
  if (!exists) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  select.value = value;
}

function syncProfile() {
  document.getElementById("profileRole").textContent = document.getElementById("role").value;
  document.getElementById("profileDepartment").textContent = document.getElementById("department").value;
  document.getElementById("profileClearance").textContent = document.getElementById("clearance").value;
}

function setAdminGuardStatus(status) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  const guard = document.getElementById("guardStatus");
  const guardCard = guard.closest(".guard-card");
  guard.textContent = normalized;
  guardCard.classList.toggle("blocked", ["BLOCKED", "DENIED"].includes(normalized));
  guardCard.classList.toggle("error", ["ERROR", "FAILED", "FAILURE"].includes(normalized));
  guardCard.classList.toggle("running", ["RUNNING", "PENDING", "WAITING"].includes(normalized));
}

function setAdminProgress(message) {
  const target = document.getElementById("adminProgress");
  if (target) {
    target.textContent = message;
  }
}

function startAdminProgress() {
  stopAdminProgress();
  const steps = [
    {status: "RUNNING", message: "Databricks Job 실행 요청을 전송 중입니다."},
    {status: "RUNNING", message: "Role과 pre-check 조건을 확인 중입니다."},
    {status: "RUNNING", message: "SQL 검색과 Vector/RAG 근거를 조회 중입니다."},
    {status: "RUNNING", message: "LLM 답변을 생성 중입니다."},
    {status: "RUNNING", message: "post-check와 조회 출처를 정리 중입니다."}
  ];
  let index = 0;
  const renderStep = () => {
    const step = steps[Math.min(index, steps.length - 1)];
    setAdminGuardStatus(step.status);
    setAdminProgress(step.message);
    index += 1;
  };
  renderStep();
  adminProgressTimer = window.setInterval(renderStep, 4500);
}

function stopAdminProgress() {
  if (adminProgressTimer) {
    window.clearInterval(adminProgressTimer);
    adminProgressTimer = null;
  }
}

async function simulate() {
  const queryInput = document.getElementById("query");
  const payload = {
    role_id: document.getElementById("role").value,
    department_name: document.getElementById("department").value,
    security_clearance: document.getElementById("clearance").value,
    query: queryInput.value.trim(),
    rbac_enabled: document.getElementById("simRbacEnabled").checked,
    pre_check_enabled: document.getElementById("simRbacEnabled").checked,
    post_check_enabled: document.getElementById("simPostCheckEnabled").checked
  };

  if (!payload.query) {
    return;
  }
  queryInput.value = "";

  const resultTarget = document.getElementById("result");
  startAdminProgress();
  updateCheckStatus("sim", {
    rbac_enabled: payload.rbac_enabled,
    pre_check: payload.pre_check_enabled ? "RUNNING" : "SKIPPED",
    post_check: payload.post_check_enabled ? "WAITING" : "SKIPPED"
  });
  resultTarget.innerHTML = `
    <article class="result-card question">
      <h3>질문</h3>
      <p>${escapeHtml(payload.query)}</p>
    </article>
    <article class="result-card answer">
      <div class="message-meta">
        <span>Admin Chat</span>
        <strong class="status-pill running">RUNNING</strong>
      </div>
      <h3>처리 중</h3>
      <div class="progress-steps">
        <span>요청 전송</span>
        <span>SQL 검색중</span>
        <span>답변 생성중</span>
        <span>결과 정리중</span>
      </div>
      <p>Databricks Job 응답을 기다리는 중입니다.</p>
    </article>
  `;

  try {
    const response = await fetch("/api/admin/simulate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });

    const data = await parseJsonResponse(response);
    if (!response.ok) {
      throw new Error(data.detail || data.message || `HTTP ${response.status}`);
    }

    rememberAdminResponse(data, "admin-chat-success");
    stopAdminProgress();
    setAdminGuardStatus(data.guard_status || "UNKNOWN");
    setAdminProgress(data.blocked ? "권한 또는 guard 조건으로 답변이 차단되었습니다." : "답변이 완료되었습니다.");
    updateCheckStatus("sim", data.checks || {});
    renderResult(data);
    renderAdminSources();
  } catch (error) {
    stopAdminProgress();
    const data = {
      request_id: "REQ-UI-ERROR",
      guard_status: "ERROR",
      answer_guard_status: "ERROR",
      blocked: true,
      answer: `요청 처리 중 오류가 발생했습니다: ${error.message}`,
      query: payload.query,
      role_id: payload.role_id,
      department_name: payload.department_name,
      security_clearance: payload.security_clearance,
      sources: {tables: [], documents: []},
      checks: {
        rbac_enabled: payload.rbac_enabled,
        pre_check: "ERROR",
        post_check: "ERROR"
      }
    };
    rememberAdminResponse(data, "admin-chat-error");
    setAdminGuardStatus("ERROR");
    setAdminProgress("오류가 발생했습니다. Databricks Apps 로그 또는 Job 실행 로그를 확인해 주세요.");
    updateCheckStatus("sim", data.checks);
    renderResult(data);
    renderAdminSources();
  }
}

function rememberAdminResponse(data, context) {
  lastResponse = data;
  try {
    sessionStorage.setItem("cosbelle_last_admin_response", JSON.stringify(data));
  } catch {
    // In-memory response still works.
  }
  logAdminResponse(context, data);
}

function loadSavedAdminResponse() {
  try {
    const saved = sessionStorage.getItem("cosbelle_last_admin_response");
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

function logAdminResponse(context, data) {
  const tables = getSourceTables(data);
  const documents = getSourceDocuments(data);
  console.info("[Admin Sources Debug]", {
    context,
    request_id: data?.request_id,
    guard_status: data?.guard_status,
    blocked: data?.blocked,
    table_count: tables.length,
    document_count: documents.length,
    tables,
    documents,
    raw_table_access: data?.raw?.table_access || []
  });
}

async function parseJsonResponse(response) {
  const responseText = await response.text();
  try {
    return responseText ? JSON.parse(responseText) : {};
  } catch {
    throw new Error(responseText || "Invalid JSON response");
  }
}

function renderResult(data) {
  const tables = getSourceTables(data);
  const documents = getSourceDocuments(data);
  const blockBadge = renderAccessBadge(data);

  document.getElementById("result").innerHTML = `
    <article class="result-card question">
      <h3>질문</h3>
      <p>${escapeHtml(data.query || data.raw?.question || "")}</p>
    </article>
    <article class="result-card answer">
      <div class="message-meta">
        <span>Admin Chat</span>
        <strong class="status-pill ${getStatusPillClass(data.guard_status)}">${escapeHtml(data.guard_status || "UNKNOWN")}</strong>
      </div>
      <h3>답변</h3>
      <div class="answer-body">${renderAnswer(data.answer || "")}</div>
    </article>
    <article class="result-card accent-sky">
      <h3>권한 프로필</h3>
      <p>역할: ${escapeHtml(data.role_id || data.effective_identity?.role_id || "")}</p>
      <p>부서: ${escapeHtml(data.department_name || data.effective_identity?.department_name || "")}</p>
      <p>등급: ${escapeHtml(data.security_clearance || data.effective_identity?.security_clearance || "")}</p>
    </article>
    <article class="result-card accent-lime">
      <h3>Guard</h3>
      <p><span class="badge ${getStatusBadgeClass(data.guard_status)}">${escapeHtml(data.guard_status || "UNKNOWN")}</span></p>
      <p>${blockBadge}</p>
    </article>
    <article class="result-card">
      <h3>조회 출처</h3>
      <div class="source-list">${renderSourceSections(tables, documents)}</div>
    </article>
    <article class="result-card answer">
      <h3>Pre / Post check</h3>
      <p>Pre-check: ${escapeHtml(data.checks?.pre_check || (data.checks?.rbac_enabled ? "ON" : "OFF"))}</p>
      <p>Post-check: ${escapeHtml(data.checks?.post_check || "UNKNOWN")}</p>
    </article>
  `;
}

function renderAdminSources() {
  if (!lastResponse) {
    lastResponse = loadSavedAdminResponse();
  }

  if (!lastResponse) {
    document.getElementById("requestIdBadge").textContent = "request: none";
    document.getElementById("databaseSources").textContent = "No table sources returned";
    document.getElementById("documentSources").textContent = "No document citations returned";
    document.getElementById("guardSources").textContent = "No guard result yet";
    return;
  }

  const tables = getSourceTables(lastResponse);
  const documents = getSourceDocuments(lastResponse);
  logAdminResponse("render-admin-sources", lastResponse);

  document.getElementById("requestIdBadge").textContent = `request: ${lastResponse.request_id || "local"}`;
  document.getElementById("databaseSources").innerHTML = tables.length
    ? tables.map((table) => `<div>${formatTableSource(table)}</div>`).join("")
    : '<span class="muted-empty">No table sources returned</span>';
  document.getElementById("documentSources").innerHTML = documents.length
    ? documents.map((doc) => `<div>${formatDocument(doc)}</div>`).join("")
    : '<span class="muted-empty">No document citations returned</span>';
  document.getElementById("guardSources").innerHTML = `
    <div>guard_status: ${escapeHtml(lastResponse.guard_status || "UNKNOWN")}</div>
    <div>answer_guard_status: ${escapeHtml(lastResponse.answer_guard_status || "N/A")}</div>
    <div>blocked: ${lastResponse.blocked ? "true" : "false"}</div>
    <div>pre_check_enabled: ${lastResponse.checks?.rbac_enabled ? "true" : "false"}</div>
    <div>pre_check_result: ${escapeHtml(lastResponse.checks?.pre_check || "UNKNOWN")}</div>
    <div>post_check: ${escapeHtml(lastResponse.checks?.post_check || "UNKNOWN")}</div>
    <div>table_source_count: ${escapeHtml(String(tables.length))}</div>
    <div>document_source_count: ${escapeHtml(String(documents.length))}</div>
  `;
}

async function loadRoles() {
  if (roles.length) {
    return roles;
  }

  const response = await fetch("/api/admin/roles");
  roles = await response.json();

  const options = roles.map((role) => `
    <option value="${escapeHtml(role.role_id)}">${escapeHtml(role.role_id)}</option>
  `).join("");
  document.getElementById("role").innerHTML = options;
  document.getElementById("dashboardRole").innerHTML = options;
  document.getElementById("sqlRoleFilter").innerHTML = `<option value="">전체 역할</option>${options}`;

  if (roles.length) {
    const adminRoleSelect = document.getElementById("role");
    adminRoleSelect.value = roles.some((role) => role.role_id === "MARKETING_STAFF")
      ? "MARKETING_STAFF"
      : roles[0].role_id;
    applyRoleDefaults(adminRoleSelect.value);
  }

  return roles;
}

function applyRoleDefaults(roleId) {
  const role = roles.find((item) => item.role_id === roleId);
  if (role) {
    setSelectValue("department", role.department);
    setSelectValue("clearance", role.default_clearance);
  }
  syncProfile();
}

function setSelectValue(selectId, value) {
  const select = document.getElementById(selectId);
  const exists = Array.from(select.options).some((option) => option.value === value || option.textContent === value);
  if (!exists) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  select.value = value;
}

function getSourceTables(data) {
  const sourceTables = data?.sources?.tables;
  if (Array.isArray(sourceTables) && sourceTables.length) {
    return sourceTables;
  }

  const rawTableAccess = data?.raw?.table_access;
  if (Array.isArray(rawTableAccess) && rawTableAccess.length) {
    return rawTableAccess
      .filter((item) => item && item.table)
      .map((item) => ({
        table: item.table,
        result: item.result || "UNKNOWN",
        reason: item.reason || ""
      }));
  }

  return [];
}

function getSourceDocuments(data) {
  const sourceDocuments = data?.sources?.documents;
  if (Array.isArray(sourceDocuments) && sourceDocuments.length) {
    return sourceDocuments;
  }

  const citations = data?.raw?.citations || data?.raw?.sources?.documents;
  return Array.isArray(citations) ? citations : [];
}

function renderSourceSections(tables, documents) {
  const sections = [];
  if (tables.length) {
    sections.push(`
      <div class="source-section">
        <strong>조회 table</strong>
        ${tables.map((table) => `<div>${formatTableSource(table)}</div>`).join("")}
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
  return sections.length ? sections.join("") : '<span class="muted-empty">No sources returned</span>';
}

function formatTableSource(table) {
  if (typeof table === "string") {
    return escapeHtml(table);
  }
  const status = table.result ? ` (${table.result})` : "";
  const reason = table.reason ? ` - ${table.reason}` : "";
  return escapeHtml(`${table.table || "-"}${status}${reason}`);
}

function renderAccessBadge(data) {
  const status = String(data.guard_status || data.answer_guard_status || "").toUpperCase();
  if (["ERROR", "FAILED", "FAILURE"].includes(status)) {
    return '<span class="badge red">ERROR</span>';
  }
  if (data.blocked || ["BLOCKED", "DENIED"].includes(status)) {
    return '<span class="badge red">BLOCKED</span>';
  }
  if (["RUNNING", "PENDING", "WAITING"].includes(status)) {
    return '<span class="badge yellow">RUNNING</span>';
  }
  return '<span class="badge green">ALLOWED</span>';
}

function updateCheckStatus(scope, checks) {
  if (scope !== "sim") {
    return;
  }

  const preCheck = checks.pre_check || (checks.rbac_enabled ? "ON" : "OFF");
  document.getElementById("simPreStatus").textContent = preCheck;
  document.getElementById("simPostStatus").textContent = checks.post_check || "READY";
}

async function loadDashboards() {
  const [llmResponse, databaseResponse] = await Promise.all([
    fetch("/api/admin/dashboard/llm"),
    fetch("/api/admin/dashboard/database")
  ]);

  const llmData = await llmResponse.json();
  const databaseData = await databaseResponse.json();

  renderMetrics("llmMetrics", llmData);
  renderMetrics("databaseMetrics", databaseData);
  await loadRoles();
  await loadRoleAccess(document.getElementById("dashboardRole").value);
}

async function loadRoleAccess(roleId) {
  const response = await fetch(`/api/admin/roles/${encodeURIComponent(roleId)}/access`);
  const data = await response.json();

  document.getElementById("roleAccessSummary").innerHTML = `
    <article class="role-access-card">
      <h3>Role Profile</h3>
      <p><strong>${escapeHtml(data.role_id)}</strong></p>
      <p>${escapeHtml(data.role_name)}</p>
      <p>${escapeHtml(data.description || "")}</p>
      <p>부서: ${escapeHtml(data.department || "-")}</p>
      <p>기본 등급: ${escapeHtml(data.default_clearance)}</p>
    </article>
    <article class="role-access-card">
      <h3>시스템 / 도메인</h3>
      <div class="pill-list">
        ${data.systems.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}
        ${data.domains.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}
      </div>
    </article>
    <article class="role-access-card">
      <h3>접근 table</h3>
      <div class="source-list">
        ${data.tables.map((item) => `<div>${escapeHtml(item)}</div>`).join("")}
      </div>
    </article>
    <article class="role-access-card">
      <h3>사용량</h3>
      <div class="mini-metrics">
        <div><span>Requests</span><strong>${escapeHtml(data.usage.requests)}</strong></div>
        <div><span>Completed</span><strong>${escapeHtml(data.usage.completed)}</strong></div>
        <div><span>Blocked</span><strong>${escapeHtml(data.usage.blocked)}</strong></div>
        <div><span>Failed</span><strong>${escapeHtml(data.usage.failed)}</strong></div>
      </div>
    </article>
    <article class="role-access-card">
      <h3>Guard / 차단</h3>
      <div class="mini-metrics">
        <div><span>Pre blocked</span><strong>${escapeHtml(data.usage.pre_check_blocked)}</strong></div>
        <div><span>Post blocked</span><strong>${escapeHtml(data.usage.post_check_blocked)}</strong></div>
        <div><span>No evidence</span><strong>${escapeHtml(data.usage.no_evidence)}</strong></div>
        <div><span>PASS rate</span><strong>${escapeHtml(data.usage.guard_pass_rate)}</strong></div>
      </div>
    </article>
    <article class="role-access-card">
      <h3>많이 조회된 출처</h3>
      <div class="source-list">
        ${data.top_tables.map((item) => `<div>${escapeHtml(item.table)} <strong>${escapeHtml(item.count)}</strong></div>`).join("")}
        ${data.top_documents.map((item) => `<div>${escapeHtml(item.document_id)} <strong>${escapeHtml(item.count)}</strong></div>`).join("")}
      </div>
    </article>
    <article class="role-access-card">
      <h3>차단된 접근</h3>
      <div class="source-list">
        ${data.blocked_attempts.map((item) => `<div>${escapeHtml(item.table)} <strong>${escapeHtml(item.count)}</strong></div>`).join("")}
      </div>
    </article>
  `;
}

async function loadSqlLogs(page = 1) {
  await loadRoles();
  const params = new URLSearchParams({
    page: String(page),
    page_size: "15",
    days: "7"
  });
  const dateFrom = document.getElementById("sqlDateFrom").value;
  const dateTo = document.getElementById("sqlDateTo").value;
  const role = document.getElementById("sqlRoleFilter").value;
  const status = document.getElementById("sqlStatusFilter").value;
  const source = document.getElementById("sqlSourceFilter").value;
  const table = document.getElementById("sqlTableFilter").value.trim();

  if (dateFrom) {
    params.set("date_from", dateFrom);
    params.set("days", "0");
  }
  if (dateTo) {
    params.set("date_to", dateTo);
    params.set("days", "0");
  }
  if (role) {
    params.set("role", role);
  }
  if (status) {
    params.set("status", status);
  }
  if (source) {
    params.set("source", source);
  }
  if (table) {
    params.set("table", table);
  }

  const response = await fetch(`/api/admin/sql-logs?${params.toString()}`);
  const payload = await response.json();
  sqlLogs = Array.isArray(payload) ? payload : payload.logs || [];
  sqlLogPage = Array.isArray(payload) ? 1 : payload.page || 1;
  sqlLogTotalPages = Array.isArray(payload) ? 1 : payload.total_pages || 1;
  expandedSqlLogIndex = null;

  renderSqlLogs();
  if (sqlLogs.length) {
    renderSqlLogDetail(sqlLogs[0]);
  } else {
    document.getElementById("sqlLogDetail").textContent = "조건에 맞는 로그가 없습니다.";
  }
  renderSqlLogPagination(Array.isArray(payload) ? sqlLogs.length : payload.total || 0);
}

function getStatusBadgeClass(status) {
  const normalized = String(status || "").toUpperCase();
  if (["BLOCKED", "DENIED", "ERROR", "FAILED", "FAILURE"].includes(normalized)) {
    return "red";
  }
  if (["RUNNING", "PENDING", "WAITING"].includes(normalized)) {
    return "yellow";
  }
  return "green";
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

function formatKoreanTime(value) {
  if (!value) {
    return "-";
  }

  const raw = String(value).trim();
  return raw
    .replace("T", " ")
    .replace(/\.\d+/, "")
    .replace(/\s*([zZ]|[+-]\d{2}:?\d{2})$/, "");
}

function renderMetrics(targetId, data) {
  document.getElementById(targetId).innerHTML = Object.entries(data)
    .map(([key, value]) => `
      <div class="metric">
        <span>${escapeHtml(key)}</span>
        <strong>${escapeHtml(String(value))}</strong>
      </div>
    `)
    .join("");
}

function formatDocument(doc) {
  if (typeof doc === "string") {
    return escapeHtml(doc);
  }
  const parts = [doc.document_id, doc.chunk_id, doc.classification].filter(Boolean);
  return escapeHtml(parts.join(" / "));
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

loadRoles();
syncProfile();

function renderSqlLogPagination(total) {
  const pagination = document.querySelector(".log-pagination");
  if (!pagination) {
    return;
  }

  if (sqlLogTotalPages <= 1) {
    pagination.style.display = "none";
    return;
  }

  pagination.style.display = "flex";
  document.getElementById("sqlLogPageInfo").textContent = `Page ${sqlLogPage} / ${sqlLogTotalPages} · ${total} logs`;
  document.getElementById("prevSqlLogPage").disabled = sqlLogPage <= 1;
  document.getElementById("nextSqlLogPage").disabled = sqlLogPage >= sqlLogTotalPages;
}

function renderSqlLogs() {
  const target = document.getElementById("sqlLogRows");
  if (!sqlLogs.length) {
    target.innerHTML = '<tr><td colspan="7">조건에 맞는 로그가 없습니다.</td></tr>';
    return;
  }

  target.innerHTML = sqlLogs.map((log, index) => {
    const isExpanded = expandedSqlLogIndex === index;
    return `
      <tr data-index="${index}" class="${isExpanded ? "log-row-expanded" : ""}">
        <td>${escapeHtml(formatKoreanTime(log.query_time))}</td>
        <td><span class="badge neutral">${escapeHtml(formatChatSource(log.chat_source))}</span></td>
        <td class="log-question-cell" title="${escapeHtml(formatLogQuestion(log))}">${escapeHtml(formatLogQuestionPreview(log))}</td>
        <td>${escapeHtml(String(log.row_count))}</td>
        <td>${escapeHtml(String(log.column_count))}</td>
        <td>${escapeHtml(log.actor)}</td>
        <td><span class="badge ${getStatusBadgeClass(log.status)}">${escapeHtml(log.status)}</span></td>
      </tr>
      ${isExpanded ? renderSqlLogConversation(log) : ""}
    `;
  }).join("");

  document.querySelectorAll("#sqlLogRows tr[data-index]").forEach((row) => {
    row.addEventListener("click", () => {
      const index = Number(row.dataset.index);
      expandedSqlLogIndex = expandedSqlLogIndex === index ? null : index;
      renderSqlLogDetail(sqlLogs[index]);
      renderSqlLogs();
    });
  });
}

function renderSqlLogDetail(log) {
  document.getElementById("sqlLogDetail").innerHTML = `
    <div class="detail-row"><span>Request ID</span><strong>${escapeHtml(log.request_id)}</strong></div>
    <div class="detail-row"><span>조회 시간</span><strong>${escapeHtml(formatKoreanTime(log.query_time))}</strong></div>
    <div class="detail-row"><span>채팅 출처</span><strong>${escapeHtml(formatChatSource(log.chat_source))}</strong></div>
    <div class="detail-row"><span>질문</span><strong>${escapeHtml(formatLogQuestion(log))}</strong></div>
    <div class="detail-row"><span>Table</span><strong>${escapeHtml(log.table_name)}</strong></div>
    <div class="detail-row"><span>Rows</span><strong>${escapeHtml(String(log.row_count))}</strong></div>
    <div class="detail-row"><span>Columns</span><strong>${escapeHtml((log.columns || []).join(", "))}</strong></div>
    <div class="detail-row"><span>Actor</span><strong>${escapeHtml(log.actor)}</strong></div>
    <div class="detail-row"><span>Status</span><strong>${escapeHtml(log.status)}</strong></div>
    <div class="detail-row"><span>SQL</span><code>${escapeHtml(log.sql)}</code></div>
  `;
}

function renderSqlLogConversation(log) {
  const answer = formatLogAnswer(log);
  return `
    <tr class="log-conversation-row">
      <td colspan="7">
        <section class="log-conversation">
          <div class="log-conversation-header">
            <strong>대화 기록</strong>
            <span class="badge ${getStatusBadgeClass(log.status)}">${escapeHtml(log.status || "UNKNOWN")}</span>
          </div>
          <div class="log-conversation-turn user-turn">
            <span>Question</span>
            <p>${escapeHtml(formatLogQuestion(log))}</p>
          </div>
          <div class="log-conversation-turn assistant-turn">
            <span>Response</span>
            ${answer ? `<div class="answer-body">${renderAnswer(answer)}</div>` : "<p>이 로그에는 아직 LLM 답변 기록이 없습니다. 새 노트북으로 실행된 로그부터 표시됩니다.</p>"}
          </div>
        </section>
      </td>
    </tr>
  `;
}

function formatLogQuestion(log) {
  const question = log?.question || log?.user_question || log?.query || log?.raw_question || "";
  return String(question || log?.table_name || "-");
}

function formatLogQuestionPreview(log, maxLength = 42) {
  const question = formatLogQuestion(log).replace(/\s+/g, " ").trim();
  if (question.length <= maxLength) {
    return question;
  }
  return `${question.slice(0, maxLength).trimEnd()}...`;
}

function formatLogAnswer(log) {
  const answer = log?.llm_answer || log?.answer || log?.response || log?.summary || "";
  return String(answer || "");
}

function formatChatSource(value) {
  const source = String(value || "").toLowerCase();
  if (source === "user") {
    return "공통 Chat";
  }
  if (source === "admin_simulation") {
    return "Admin Chat";
  }
  return value || "-";
}

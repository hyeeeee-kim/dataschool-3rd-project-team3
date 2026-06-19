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
let roles = [];
let dashboardRoles = [];
let currentDashboardData = null;
let adminProgressTimer = null;

document.querySelectorAll(".side-nav button").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.target, button));
});

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
  loadDataDashboard(event.target.value);
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
      <p>진행 상황을 확인하고 있습니다. Databricks Job 응답을 기다리는 중입니다.</p>
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
  await loadDashboardRoles();
  await loadDataDashboard(document.getElementById("dashboardRole").value);
}

async function loadDashboardRoles() {
  const response = await fetch("/api/admin/data-dashboard/roles");
  const data = await response.json();
  dashboardRoles = data.roles || [];

  const target = document.getElementById("dashboardRole");
  const previousValue = target.value;
  target.innerHTML = dashboardRoles.map((role) => `
    <option value="${escapeHtml(role.role_id)}">${escapeHtml(role.label)} · ${escapeHtml(role.role_id)}</option>
  `).join("");

  if (dashboardRoles.some((role) => role.role_id === previousValue)) {
    target.value = previousValue;
  } else if (dashboardRoles.length) {
    target.value = dashboardRoles[0].role_id;
  }

}

async function loadDataDashboard(roleId) {
  const target = document.getElementById("roleAccessSummary");
  if (!roleId) {
    target.innerHTML = '<div class="empty-state">선택 가능한 역할이 없습니다.</div>';
    return;
  }

  target.innerHTML = '<div class="empty-state">Databricks SQL Warehouse에서 대시보드 데이터를 조회하는 중입니다.</div>';

  const response = await fetch(`/api/admin/data-dashboard/${encodeURIComponent(roleId)}`);
  const data = await response.json();
  currentDashboardData = data;

  renderDataDashboard(data);
}

function renderDataDashboard(data) {
  const target = document.getElementById("roleAccessSummary");
  const commonMetrics = addDashboardGroup(data.common_metrics || [], "common");
  const roleMetrics = addDashboardGroup(data.role_metrics || [], "role");
  const allMetrics = [...commonMetrics, ...roleMetrics];
  const successCount = allMetrics.filter((metric) => metric.status === "SUCCESS").length;
  const failedCount = allMetrics.length - successCount;
  const tableCount = new Set(allMetrics.map((metric) => metric.table).filter(Boolean)).size;

  target.innerHTML = `
    <article class="role-access-card dashboard-profile-card">
      <span class="card-kicker">Role Profile</span>
      <h3>${escapeHtml(data.label)}</h3>
      <p><strong>${escapeHtml(data.role_id)}</strong> · ${escapeHtml(data.role_name)}</p>
      <div class="dashboard-chip-row">
        <span>${escapeHtml(data.department || "-")}</span>
        <span>${escapeHtml(data.default_clearance || "-")}</span>
      </div>
    </article>
    <article class="role-access-card dashboard-summary-card">
      <span class="card-kicker">Query Status</span>
      <h3>조회 상태</h3>
      <div class="mini-metrics">
        <div><span>전체 지표</span><strong>${escapeHtml(allMetrics.length)}</strong></div>
        <div><span>성공</span><strong>${escapeHtml(successCount)}</strong></div>
        <div><span>실패/미설정</span><strong>${escapeHtml(failedCount)}</strong></div>
        <div><span>테이블</span><strong>${escapeHtml(tableCount)}</strong></div>
      </div>
    </article>
    <article class="role-access-card dashboard-note-card">
      <span class="card-kicker">Rules</span>
      <h3>표시 기준</h3>
      <div class="source-list">
        ${(data.notes || []).map((note) => `<div>${escapeHtml(note)}</div>`).join("")}
      </div>
    </article>
    ${renderDashboardSection("전사 공통", commonMetrics, "전 역할에서 같이 보는 업무 기준 지표입니다.")}
    ${renderDashboardSection(`${data.label} 전용`, roleMetrics, "선택한 역할의 업무 권한과 가까운 지표입니다.")}
  `;
}

function addDashboardGroup(metrics, group) {
  return metrics.map((metric) => ({...metric, group}));
}

function renderDashboardSection(title, metrics, description) {
  return `
    <div class="dashboard-section-title">
      <div>
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(description)}</span>
      </div>
    </div>
    ${metrics.map(renderDashboardMetric).join("") || '<div class="empty-state">조건에 맞는 지표가 없습니다.</div>'}
  `;
}

function renderDashboardMetric(metric) {
  const statusClass = metric.status === "SUCCESS" ? "green" : "red";
  const rows = metric.rows || [];
  const visualization = metric.status === "SUCCESS" ? renderDashboardVisualization(metric, rows) : "";
  return `
    <article class="role-access-card db-metric-card">
      <div class="db-metric-heading">
        <div>
          <h3>${escapeHtml(metric.title)}</h3>
          <p>${escapeHtml(metric.table)} · ${escapeHtml(metric.visualization)}</p>
        </div>
        <span class="badge ${statusClass}">${escapeHtml(metric.status)}</span>
      </div>
      ${metric.status === "SUCCESS"
        ? `${visualization}${renderDashboardRows(metric.columns || [], rows)}`
        : `<div class="empty-state">${escapeHtml(metric.error || "조회 결과가 없습니다.")}</div>`}
    </article>
  `;
}

function renderDashboardVisualization(metric, rows) {
  if (!rows.length) {
    return "";
  }

  const columns = metric.columns || Object.keys(rows[0] || {});
  const numericColumns = columns.filter((column) => rows.some((row) => toNumber(row[column]) !== null));
  if (!numericColumns.length) {
    return renderTimelinePreview(metric, rows, columns);
  }

  const visual = String(metric.visualization || "").toLowerCase();
  if (visual.includes("목록")) {
    return renderListPreview(metric, rows, columns);
  }
  if (visual.includes("히트맵")) {
    return renderHeatmapPreview(rows, columns, numericColumns);
  }
  if (visual.includes("트리맵")) {
    return renderTreemapPreview(rows, columns, numericColumns);
  }
  if (visual.includes("퍼널")) {
    return renderFunnelPreview(rows, columns, numericColumns);
  }
  if (visual.includes("산점도")) {
    if (numericColumns.length < 2) {
      return renderHeatmapPreview(rows, columns, numericColumns);
    }
    return renderScatterPreview(rows, columns, numericColumns);
  }
  if (visual.includes("간트")) {
    return renderGanttPreview(metric, rows, columns);
  }
  if (visual.includes("스택")) {
    return renderStackedBarPreview(rows, columns, numericColumns);
  }
  if (visual.includes("상태 바")) {
    return renderStatusBarPreview(rows, columns, numericColumns);
  }
  if (visual.includes("게이지") || visual.includes("kpi") || visual.includes("스코어")) {
    return renderGaugePreview(rows, columns, numericColumns);
  }
  if (visual.includes("도넛")) {
    return renderDonutPreview(rows, columns, numericColumns);
  }
  if (visual.includes("라인")) {
    return renderLinePreview(rows, columns, numericColumns);
  }
  if (visual.includes("캘린더")) {
    return renderCalendarPreview(metric, rows, columns);
  }
  if (visual.includes("타임라인")) {
    return renderTimelinePreview(metric, rows, columns);
  }
  if (visual.includes("테이블")) {
    return renderTablePreview(rows, columns);
  }
  return renderBarPreview(rows, columns, numericColumns);
}

function renderListPreview(metric, rows, columns) {
  const titleColumn = columns.find((column) => /name|title|type|event/i.test(column)) || columns[0];
  const statusColumn = columns.find((column) => /status|approval|state/i.test(column));
  const countColumn = columns.find((column) => /count|total|qty|quantity/i.test(column));

  return `
    <div class="mini-chart event-list-chart">
      ${rows.slice(0, 8).map((row) => `
        <div class="event-list-row">
          <div>
            <strong>${escapeHtml(row[titleColumn] ?? metric.title)}</strong>
            ${statusColumn ? `<span>${escapeHtml(row[statusColumn] ?? "-")}</span>` : ""}
          </div>
          ${countColumn ? `<em>${escapeHtml(formatNumber(row[countColumn]))}</em>` : ""}
        </div>
      `).join("")}
    </div>
  `;
}

function renderTablePreview(rows, columns) {
  const previewColumns = columns.slice(0, 4);
  return `
    <div class="mini-chart table-preview-chart">
      ${rows.slice(0, 5).map((row) => `
        <div class="table-preview-row">
          ${previewColumns.map((column) => `
            <div>
              <span>${escapeHtml(column)}</span>
              <strong>${escapeHtml(row[column] ?? "-")}</strong>
            </div>
          `).join("")}
        </div>
      `).join("")}
    </div>
  `;
}

function renderHeatmapPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const rowColumn = columns.find((column) => column !== valueColumn) || columns[0];
  const columnColumn = columns.find((column) => column !== valueColumn && column !== rowColumn) || rowColumn;
  const rowLabels = [...new Set(rows.map((row) => row[rowColumn] ?? "-"))].slice(0, 6);
  const columnLabels = [...new Set(rows.map((row) => row[columnColumn] ?? "-"))].slice(0, 6);
  const maxValue = Math.max(...rows.map((row) => Math.abs(toNumber(row[valueColumn]) || 0)), 1);

  return `
    <div class="mini-chart heatmap-chart">
      <div class="heatmap-grid" style="--heatmap-cols:${columnLabels.length}">
        <span class="heatmap-axis"></span>
        ${columnLabels.map((label) => `<span class="heatmap-axis">${escapeHtml(label)}</span>`).join("")}
        ${rowLabels.map((rowLabel) => `
          <span class="heatmap-axis heatmap-row-label">${escapeHtml(rowLabel)}</span>
          ${columnLabels.map((columnLabel) => {
            const match = rows.find((row) => String(row[rowColumn] ?? "-") === String(rowLabel) && String(row[columnColumn] ?? "-") === String(columnLabel));
            const value = toNumber(match?.[valueColumn]) || 0;
            const intensity = Math.max(value / maxValue, 0.12);
            return `<span class="heatmap-cell" style="--intensity:${intensity}"><strong>${escapeHtml(formatNumber(value))}</strong></span>`;
          }).join("")}
        `).join("")}
      </div>
    </div>
  `;
}

function renderTreemapPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const chartRows = rows
    .map((row) => ({
      label: formatChartLabel(row, labelColumn, columns),
      value: Math.max(toNumber(row[valueColumn]) || 0, 0)
    }))
    .slice(0, 8);
  const total = chartRows.reduce((sum, row) => sum + row.value, 0) || 1;

  return `
    <div class="mini-chart treemap-chart">
      ${chartRows.map((row, index) => {
        const weight = Math.max((row.value / total) * 100, 12);
        return `
          <div class="tree-tile stack-color-${index % 5}" style="flex-basis:${weight}%">
            <strong>${escapeHtml(row.label)}</strong>
            <span>${escapeHtml(formatNumber(row.value))}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderFunnelPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const chartRows = rows
    .map((row) => ({
      label: formatChartLabel(row, labelColumn, columns),
      value: Math.max(toNumber(row[valueColumn]) || 0, 0)
    }))
    .slice(0, 6);
  const maxValue = Math.max(...chartRows.map((row) => row.value), 1);

  return `
    <div class="mini-chart funnel-chart">
      ${chartRows.map((row, index) => {
        const width = Math.max((row.value / maxValue) * 100, 18);
        return `
          <div class="funnel-step" style="width:${width}%">
            <span>${escapeHtml(index + 1)}</span>
            <strong>${escapeHtml(row.label)}</strong>
            <em>${escapeHtml(formatNumber(row.value))}</em>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderScatterPreview(rows, columns, numericColumns) {
  const hasTwoNumericAxes = numericColumns.length > 1;
  const xColumn = hasTwoNumericAxes ? numericColumns[0] : "category_index";
  const yColumn = hasTwoNumericAxes ? numericColumns[1] : numericColumns[0];
  const labelColumn = chooseLabelColumn(columns, yColumn);
  const values = rows.slice(0, 12).map((row, index) => ({
    label: formatChartLabel(row, labelColumn, columns),
    x: hasTwoNumericAxes ? toNumber(row[xColumn]) || 0 : index + 1,
    y: toNumber(row[yColumn]) || 0
  }));
  const maxX = hasTwoNumericAxes ? Math.max(...values.map((point) => Math.abs(point.x)), 1) : Math.max(values.length, 1);
  const maxY = Math.max(...values.map((point) => Math.abs(point.y)), 1);

  return `
    <div class="mini-chart scatter-chart">
      <div class="scatter-plot">
        ${values.map((point, index) => {
          const left = hasTwoNumericAxes
            ? Math.min(Math.max((Math.abs(point.x) / maxX) * 86 + 7, 7), 93)
            : values.length === 1 ? 50 : 8 + (index / (values.length - 1)) * 84;
          const bottom = Math.min(Math.max((Math.abs(point.y) / maxY) * 78 + 10, 10), 88);
          return `<span class="stack-color-${index % 5}" style="left:${left}%; bottom:${bottom}%" title="${escapeHtml(point.label)}"></span>`;
        }).join("")}
      </div>
      <div class="scatter-meta"><span>${escapeHtml(hasTwoNumericAxes ? xColumn : labelColumn)}</span><strong>${escapeHtml(yColumn)}</strong></div>
      <div class="scatter-legend">
        ${values.map((point, index) => `<span><i class="stack-color-${index % 5}"></i>${escapeHtml(point.label)}</span>`).join("")}
      </div>
    </div>
  `;
}

function renderGanttPreview(metric, rows, columns) {
  const titleColumn = columns.find((column) => /name|supplier|vendor|order|po|delivery|status/i.test(column)) || columns[0];
  const dateColumns = columns.filter((column) => /date|period|eta|due|planned|actual/i.test(column));
  const startColumn = dateColumns[0];
  const endColumn = dateColumns[1] || dateColumns[0];

  if (!startColumn) {
    return renderListPreview(metric, rows, columns);
  }

  return `
    <div class="mini-chart gantt-chart">
      ${rows.slice(0, 6).map((row, index) => `
        <div class="gantt-row">
          <strong>${escapeHtml(row[titleColumn] ?? metric.title)}</strong>
          <div><i class="stack-color-${index % 5}" style="left:${8 + (index % 4) * 10}%; width:${42 + (index % 3) * 12}%"></i></div>
          <span>${escapeHtml(row[startColumn] ?? "-")}${endColumn !== startColumn ? ` ~ ${escapeHtml(row[endColumn] ?? "-")}` : ""}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderStackedBarPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const segmentColumn = columns.find((column) => column !== valueColumn && column !== labelColumn) || labelColumn;
  const grouped = new Map();

  rows.forEach((row) => {
    const label = row[labelColumn] ?? "-";
    const segment = row[segmentColumn] ?? "-";
    const value = toNumber(row[valueColumn]) || 0;
    if (!grouped.has(label)) {
      grouped.set(label, {label, segments: [], total: 0});
    }
    grouped.get(label).segments.push({segment, value});
    grouped.get(label).total += value;
  });

  const chartRows = [...grouped.values()].slice(0, 6);
  const maxTotal = Math.max(...chartRows.map((row) => Math.abs(row.total)), 1);

  return `
    <div class="mini-chart stacked-chart">
      ${chartRows.map((row) => `
        <div class="stacked-row">
          <span>${escapeHtml(row.label)}</span>
          <div class="stacked-track">
            ${row.segments.map((segment, index) => {
              const width = Math.max((Math.abs(segment.value) / maxTotal) * 100, 4);
              return `<i class="stack-color-${index % 5}" style="width:${width}%" title="${escapeHtml(segment.segment)}"></i>`;
            }).join("")}
          </div>
          <strong>${escapeHtml(formatNumber(row.total))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderStatusBarPreview(rows, columns, numericColumns) {
  const labelColumn = chooseLabelColumn(columns, numericColumns[0]);
  const valueColumns = numericColumns.slice(0, 2);
  const maxValue = Math.max(...rows.flatMap((row) => valueColumns.map((column) => Math.abs(toNumber(row[column]) || 0))), 1);

  return `
    <div class="mini-chart status-chart">
      ${rows.slice(0, 6).map((row) => `
        <div class="status-row">
          <strong>${escapeHtml(formatChartLabel(row, labelColumn, columns))}</strong>
          ${valueColumns.map((column, index) => {
            const value = toNumber(row[column]) || 0;
            const width = Math.max((Math.abs(value) / maxValue) * 100, 3);
            return `
              <div class="status-meter">
                <span>${escapeHtml(column)}</span>
                <div><i class="stack-color-${index}" style="width:${width}%"></i></div>
                <em>${escapeHtml(formatNumber(value))}</em>
              </div>
            `;
          }).join("")}
        </div>
      `).join("")}
    </div>
  `;
}

function renderCalendarPreview(metric, rows, columns) {
  const dateColumn = columns.find((column) => /date|period|month/i.test(column));
  const titleColumn = columns.find((column) => /name|title|product/i.test(column)) || columns[0];
  const metaColumn = columns.find((column) => column !== dateColumn && column !== titleColumn) || titleColumn;
  if (!dateColumn) {
    return renderTimelinePreview(metric, rows, columns);
  }

  return `
    <div class="mini-chart calendar-chart">
      ${rows.slice(0, 6).map((row) => {
        const dateText = String(row[dateColumn] ?? "-");
        const parts = dateText.split("-");
        return `
          <div class="calendar-card">
            <div>
              <span>${escapeHtml(parts[1] || dateText)}</span>
              <strong>${escapeHtml(parts[2] || "")}</strong>
            </div>
            <p>${escapeHtml(row[titleColumn] ?? metric.title)}</p>
            <small>${escapeHtml(row[metaColumn] ?? "")}</small>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderBarPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const chartRows = rows
    .map((row) => ({
      label: formatChartLabel(row, labelColumn, columns),
      value: toNumber(row[valueColumn]) || 0
    }))
    .slice(0, 6);
  const maxValue = Math.max(...chartRows.map((row) => Math.abs(row.value)), 1);

  return `
    <div class="mini-chart bar-chart">
      ${chartRows.map((row) => {
        const width = Math.max((Math.abs(row.value) / maxValue) * 100, 3);
        return `
          <div class="bar-row">
            <span class="bar-label">${escapeHtml(row.label)}</span>
            <div class="bar-track"><span class="bar-fill" style="width:${width}%"></span></div>
            <strong>${escapeHtml(formatNumber(row.value))}</strong>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderGaugePreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const values = rows.map((row) => toNumber(row[valueColumn])).filter((value) => value !== null);
  const total = values.reduce((sum, value) => sum + value, 0);
  const maxValue = Math.max(...values.map((value) => Math.abs(value)), 1);
  const percent = Math.min(Math.round((Math.abs(total) / Math.max(maxValue, Math.abs(total))) * 100), 100);

  return `
    <div class="mini-chart gauge-chart">
      <div class="gauge-ring" style="--gauge:${percent}%">
        <strong>${escapeHtml(formatNumber(total))}</strong>
        <span>${escapeHtml(valueColumn)}</span>
      </div>
      <div class="gauge-list">
        ${rows.slice(0, 4).map((row) => `
          <div><span>${escapeHtml(formatChartLabel(row, labelColumn, columns))}</span><strong>${escapeHtml(formatNumber(toNumber(row[valueColumn]) || 0))}</strong></div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderDonutPreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const labelColumn = chooseLabelColumn(columns, valueColumn);
  const allRows = rows
    .map((row) => ({
      label: formatChartLabel(row, labelColumn, columns),
      value: Math.max(toNumber(row[valueColumn]) || 0, 0)
    }))
    .filter((row) => row.value > 0);
  const visibleRows = allRows.slice(0, 5);
  const hiddenTotal = allRows.slice(5).reduce((sum, row) => sum + row.value, 0);
  const chartRows = hiddenTotal > 0
    ? [...visibleRows.slice(0, 4), {label: "기타", value: hiddenTotal}]
    : visibleRows;
  const total = chartRows.reduce((sum, row) => sum + row.value, 0) || 1;
  let current = 0;
  const segments = chartRows.flatMap((row, index) => {
    const start = current;
    const end = current + (row.value / total) * 100;
    current = end;
    const gap = chartRows.length > 1 ? Math.min(0.85, Math.max((end - start) * 0.12, 0.25)) : 0;
    const colorEnd = Math.max(start, end - gap);
    return [
      `var(--chart-${index % 5}) ${start}% ${colorEnd}%`,
      `var(--surface) ${colorEnd}% ${end}%`
    ];
  }).join(", ");

  return `
    <div class="mini-chart donut-chart">
      <div class="donut-ring" style="--segments:${segments}">
        <strong>${escapeHtml(formatNumber(total))}</strong>
        <span>${escapeHtml(valueColumn)}</span>
      </div>
      <div class="donut-list">
        ${chartRows.map((row, index) => {
          const percent = Math.round((row.value / total) * 100);
          return `
            <div class="donut-row">
              <i class="donut-marker stack-color-${index % 5}"></i>
              <span>${escapeHtml(row.label)}</span>
              <div class="donut-track"><span class="stack-color-${index % 5}" style="width:${Math.max(percent, 3)}%"></span></div>
              <strong>${escapeHtml(formatNumber(row.value))}</strong>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function renderLinePreview(rows, columns, numericColumns) {
  const valueColumn = chooseValueColumn(numericColumns);
  const values = rows.map((row) => toNumber(row[valueColumn]) || 0).slice(0, 12);
  const maxValue = Math.max(...values.map((value) => Math.abs(value)), 1);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100;
    const y = 90 - (Math.abs(value) / maxValue) * 75;
    return `${x},${y}`;
  }).join(" ");

  return `
    <div class="mini-chart line-chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <polyline points="${points}" />
      </svg>
      <div class="line-meta"><span>${escapeHtml(valueColumn)}</span><strong>${escapeHtml(values.map(formatNumber).join(" -> "))}</strong></div>
    </div>
  `;
}

function renderTimelinePreview(metric, rows, columns) {
  const dateColumn = columns.find((column) => /date|period|month/i.test(column));
  const labelColumn = columns.find((column) => /name|title|status|type/i.test(column)) || columns[0];
  if (!dateColumn) {
    return "";
  }

  return `
    <div class="mini-chart timeline-chart">
      ${rows.slice(0, 5).map((row) => `
        <div class="timeline-row">
          <span>${escapeHtml(row[dateColumn] ?? "-")}</span>
          <strong>${escapeHtml(row[labelColumn] ?? metric.title)}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderDashboardRows(columns, rows) {
  if (!rows.length) {
    return '<div class="empty-state">조회된 행이 없습니다.</div>';
  }

  const visibleRows = rows.slice(0, 8);
  return `
    <details class="dashboard-detail-table">
      <summary>상세 데이터 보기 · ${escapeHtml(rows.length)} rows${rows.length > visibleRows.length ? " · first 8 shown" : ""}</summary>
      <div class="dashboard-table-wrap">
        <table class="dashboard-table">
          <thead>
            <tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
          </thead>
          <tbody>
            ${visibleRows.map((row) => `
              <tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "")}</td>`).join("")}</tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </details>
  `;
}

function chooseValueColumn(numericColumns) {
  return numericColumns.find((column) => /count|total|sum|amount|sales|quantity|units|rate|score|headcount|clicks|impressions|overdue/i.test(column))
    || numericColumns[numericColumns.length - 1];
}

function chooseLabelColumn(columns, valueColumn) {
  return columns.find((column) => column !== valueColumn && /name|status|type|severity|department|platform|channel|line|period|grade|category|product/i.test(column))
    || columns.find((column) => column !== valueColumn)
    || columns[0];
}

function formatChartLabel(row, labelColumn, columns) {
  const secondaryColumn = columns.find((column) => column !== labelColumn && /status|type|severity|channel|period|line/i.test(column));
  const label = row[labelColumn] ?? "-";
  const secondary = secondaryColumn && row[secondaryColumn] !== undefined ? ` · ${row[secondaryColumn]}` : "";
  return `${label}${secondary}`;
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const number = Number(String(value).replaceAll(",", ""));
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value ?? "-");
  }
  return new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 2}).format(number);
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

  renderSqlLogs();
  if (sqlLogs.length) {
    renderSqlLogDetail(sqlLogs[0]);
  } else {
    document.getElementById("sqlLogDetail").textContent = "조건에 맞는 로그가 없습니다.";
  }
  renderSqlLogPagination(Array.isArray(payload) ? sqlLogs.length : payload.total || 0);
}

function renderSqlLogs() {
  const target = document.getElementById("sqlLogRows");
  if (!sqlLogs.length) {
    target.innerHTML = '<tr><td colspan="6">조건에 맞는 로그가 없습니다.</td></tr>';
    return;
  }

  target.innerHTML = sqlLogs.map((log, index) => `
    <tr data-index="${index}">
      <td>${escapeHtml(formatKoreanTime(log.query_time))}</td>
      <td>${escapeHtml(log.table_name)}</td>
      <td>${escapeHtml(String(log.row_count))}</td>
      <td>${escapeHtml(String(log.column_count))}</td>
      <td>${escapeHtml(log.actor)}</td>
      <td><span class="badge ${getStatusBadgeClass(log.status)}">${escapeHtml(log.status)}</span></td>
    </tr>
  `).join("");

  document.querySelectorAll("#sqlLogRows tr").forEach((row) => {
    row.addEventListener("click", () => {
      renderSqlLogDetail(sqlLogs[Number(row.dataset.index)]);
    });
  });
}

function renderSqlLogPagination(total) {
  document.getElementById("sqlLogPageInfo").textContent = `Page ${sqlLogPage} / ${sqlLogTotalPages} · ${total} logs`;
  document.getElementById("prevSqlLogPage").disabled = sqlLogPage <= 1;
  document.getElementById("nextSqlLogPage").disabled = sqlLogPage >= sqlLogTotalPages;
}

function renderSqlLogDetail(log) {
  document.getElementById("sqlLogDetail").innerHTML = `
    <div class="detail-row"><span>Request ID</span><strong>${escapeHtml(log.request_id)}</strong></div>
    <div class="detail-row"><span>조회 시간</span><strong>${escapeHtml(formatKoreanTime(log.query_time))}</strong></div>
    <div class="detail-row"><span>Table</span><strong>${escapeHtml(log.table_name)}</strong></div>
    <div class="detail-row"><span>Rows</span><strong>${escapeHtml(String(log.row_count))}</strong></div>
    <div class="detail-row"><span>Columns</span><strong>${escapeHtml((log.columns || []).join(", "))}</strong></div>
    <div class="detail-row"><span>Actor</span><strong>${escapeHtml(log.actor)}</strong></div>
    <div class="detail-row"><span>Status</span><strong>${escapeHtml(log.status)}</strong></div>
    <div class="detail-row"><span>SQL</span><code>${escapeHtml(log.sql)}</code></div>
  `;
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

  target.innerHTML = sqlLogs.map((log, index) => `
    <tr data-index="${index}">
      <td>${escapeHtml(formatKoreanTime(log.query_time))}</td>
      <td><span class="badge neutral">${escapeHtml(formatChatSource(log.chat_source))}</span></td>
      <td>${escapeHtml(log.table_name)}</td>
      <td>${escapeHtml(String(log.row_count))}</td>
      <td>${escapeHtml(String(log.column_count))}</td>
      <td>${escapeHtml(log.actor)}</td>
      <td><span class="badge ${getStatusBadgeClass(log.status)}">${escapeHtml(log.status)}</span></td>
    </tr>
  `).join("");

  document.querySelectorAll("#sqlLogRows tr").forEach((row) => {
    row.addEventListener("click", () => {
      renderSqlLogDetail(sqlLogs[Number(row.dataset.index)]);
    });
  });
}

function renderSqlLogDetail(log) {
  document.getElementById("sqlLogDetail").innerHTML = `
    <div class="detail-row"><span>Request ID</span><strong>${escapeHtml(log.request_id)}</strong></div>
    <div class="detail-row"><span>조회 시간</span><strong>${escapeHtml(formatKoreanTime(log.query_time))}</strong></div>
    <div class="detail-row"><span>채팅 출처</span><strong>${escapeHtml(formatChatSource(log.chat_source))}</strong></div>
    <div class="detail-row"><span>Table</span><strong>${escapeHtml(log.table_name)}</strong></div>
    <div class="detail-row"><span>Rows</span><strong>${escapeHtml(String(log.row_count))}</strong></div>
    <div class="detail-row"><span>Columns</span><strong>${escapeHtml((log.columns || []).join(", "))}</strong></div>
    <div class="detail-row"><span>Actor</span><strong>${escapeHtml(log.actor)}</strong></div>
    <div class="detail-row"><span>Status</span><strong>${escapeHtml(log.status)}</strong></div>
    <div class="detail-row"><span>SQL</span><code>${escapeHtml(log.sql)}</code></div>
  `;
}

function formatChatSource(value) {
  const source = String(value || "").toLowerCase();
  if (source === "user") {
    return "일반 Chat";
  }
  if (source === "admin_simulation") {
    return "Admin Chat";
  }
  return value || "-";
}

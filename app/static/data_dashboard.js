(function () {
  const colors = ["#5b43d6", "#18a05f", "#f59e0b", "#0ea5e9", "#ef476f", "#64748b", "#14b8a6", "#a855f7", "#84cc16", "#f97316", "#06b6d4", "#dc2626"];

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function toNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function compact(value) {
    const text = String(value ?? "-");
    return text.length > 26 ? `${text.slice(0, 24)}...` : text;
  }

  function metricValue(row) {
    const keys = Object.keys(row || {});
    const numericKey = keys.find((key) => /count|total|amount|sales|cost|budget|headcount|qty|quantity|score|rate|margin|impressions|clicks/i.test(key));
    if (numericKey) {
      return toNumber(row[numericKey]);
    }
    const fallbackKey = keys.find((key) => Number.isFinite(Number(row[key])));
    return fallbackKey ? toNumber(row[fallbackKey]) : 1;
  }

  function metricLabel(row) {
    const keys = Object.keys(row || {});
    const labelKeys = keys.filter((key) => !/count|total|amount|sales|cost|budget|headcount|qty|quantity|score|rate|margin|impressions|clicks/i.test(key));
    return labelKeys.slice(0, 2).map((key) => row[key]).filter(Boolean).join(" · ") || keys[0] || "-";
  }

  function statusClass(status) {
    if (status === "SUCCESS") return "";
    if (status === "NOT_CONFIGURED") return "warning";
    return "failed";
  }

  async function loadRoles() {
    const response = await fetch("/api/admin/data-dashboard/roles");
    const data = await response.json();
    const select = document.getElementById("dataDashboardRole");
    select.innerHTML = (data.roles || []).map((role) => (
      `<option value="${esc(role.role_id)}">${esc(role.label)} · ${esc(role.role_id)}</option>`
    )).join("");
    return select.value;
  }

  async function loadDashboard(roleId) {
    const status = document.getElementById("dataDashboardStatus");
    status.className = "data-dashboard-status";
    status.textContent = "Databricks 데이터를 조회하는 중입니다.";

    try {
      const response = await fetch(`/api/admin/data-dashboard/${encodeURIComponent(roleId)}`);
      const data = await response.json();
      renderDashboard(data);
    } catch (error) {
      status.className = "data-dashboard-status warning";
      status.textContent = `대시보드 조회 실패: ${error.message}`;
    }
  }

  function renderDashboard(data) {
    const status = document.getElementById("dataDashboardStatus");
    status.className = `data-dashboard-status ${data.databricks_sql_configured ? "success" : "warning"}`;
    status.textContent = data.databricks_sql_configured
      ? "Databricks SQL Warehouse 연결 상태로 실제 테이블을 조회합니다."
      : "로컬 환경에 SQL Warehouse 설정이 없어 배포 환경에서 조회됩니다.";

    document.getElementById("dataDashboardProfile").innerHTML = `
      <article class="data-profile-item"><span>Role</span><strong>${esc(data.label || data.role_id)}</strong></article>
      <article class="data-profile-item"><span>Department</span><strong>${esc(data.department || "-")}</strong></article>
      <article class="data-profile-item"><span>Clearance</span><strong>${esc(data.default_clearance || "-")}</strong></article>
      <article class="data-profile-item"><span>Allowed tables</span><strong>${esc((data.allowed_tables || []).length)}</strong></article>
    `;

    document.getElementById("dataDashboardCommon").innerHTML = renderMetrics(data.common_metrics || []);
    document.getElementById("dataDashboardRoleMetrics").innerHTML = renderMetrics(data.role_metrics || []);
  }

  function renderMetrics(metrics) {
    if (!metrics.length) {
      return '<p class="data-empty">표시할 지표가 없습니다.</p>';
    }

    return metrics.map((metric) => `
      <article class="data-metric-card">
        <div class="data-metric-head">
          <div>
            <h4 class="data-metric-title">${esc(metric.title)}</h4>
            <p class="data-metric-meta">${esc(metric.table)} · ${esc(metric.visualization)} · ${esc(metric.row_count)} rows</p>
          </div>
          <span class="data-badge ${statusClass(metric.status)}">${esc(metric.status)}</span>
        </div>
        ${metric.status === "SUCCESS" ? renderVisualization(metric) : `<p class="data-empty">${esc(metric.error || "조회 결과가 없습니다.")}</p>`}
      </article>
    `).join("");
  }

  function renderVisualization(metric) {
    const rows = metric.rows || [];
    if (!rows.length) {
      return '<p class="data-empty">조회된 행이 없습니다.</p>';
    }

    const type = String(metric.visualization || "");
    if (type.includes("도넛")) return renderDonut(rows);
    if (type.includes("히트맵")) return renderHeatmap(rows);
    if (type.includes("산점도")) return renderScatter(rows);
    if (type.includes("라인")) return renderLine(rows);
    if (type.includes("표") || type.includes("테이블")) return renderTable(rows);
    if (type.includes("목록") || type.includes("타임라인") || type.includes("간트") || type.includes("캘린더")) return renderTable(rows);
    return renderBars(rows);
  }

  function renderBars(rows) {
    const items = rows.slice(0, 8).map((row) => ({ label: metricLabel(row), value: metricValue(row) }));
    const max = Math.max(...items.map((item) => item.value), 1);
    return `
      <div class="data-chart data-bars">
        ${items.map((item) => `
          <div class="data-bar-row">
            <span title="${esc(item.label)}">${esc(compact(item.label))}</span>
            <div class="data-bar-track"><div class="data-bar-fill" style="width:${Math.max((item.value / max) * 100, 4)}%"></div></div>
            <strong>${esc(item.value.toLocaleString())}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderDonut(rows) {
    const items = rows.map((row) => ({ label: metricLabel(row), value: metricValue(row) }));
    const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
    let cursor = 0;
    const gradient = items.map((item, index) => {
      const start = cursor;
      cursor += (item.value / total) * 100;
      return `${colors[index % colors.length]} ${start}% ${cursor}%`;
    }).join(", ");

    return `
      <div class="data-chart data-donut-wrap">
        <div class="data-donut" style="background: conic-gradient(${gradient})">
          <div class="data-donut-center">
            <strong>${esc(total.toLocaleString())}</strong>
            <span>total</span>
          </div>
        </div>
        <div class="data-legend">
          ${items.map((item, index) => `
            <div class="data-legend-row">
              <span class="data-dot" style="background:${colors[index % colors.length]}"></span>
              <span>${esc(compact(item.label))}</span>
              <strong>${esc(item.value.toLocaleString())}</strong>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  function renderTable(rows) {
    const columns = Object.keys(rows[0] || {}).slice(0, 6);
    return `
      <div class="data-chart">
        <table class="data-table">
          <thead><tr>${columns.map((column) => `<th>${esc(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.slice(0, 8).map((row) => `
              <tr>${columns.map((column) => `<td>${esc(row[column])}</td>`).join("")}</tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderHeatmap(rows) {
    const items = rows.slice(0, 12).map((row) => ({ label: metricLabel(row), value: metricValue(row) }));
    const max = Math.max(...items.map((item) => item.value), 1);
    return `
      <div class="data-chart data-heatmap">
        ${items.map((item) => {
          const alpha = 0.35 + (item.value / max) * 0.55;
          return `<div class="data-heat-cell" style="background:rgba(91,67,214,${alpha})">${esc(compact(item.label))}<br>${esc(item.value.toLocaleString())}</div>`;
        }).join("")}
      </div>
    `;
  }

  function renderScatter(rows) {
    const points = rows.slice(0, 24).map((row, index) => {
      const value = metricValue(row);
      const x = rows.length <= 1 ? 50 : 8 + (index / Math.max(rows.length - 1, 1)) * 84;
      const y = 92 - Math.min(value, Math.max(...rows.map(metricValue), 1)) / Math.max(...rows.map(metricValue), 1) * 84;
      return `<circle cx="${x}" cy="${y}" r="4.5" fill="${colors[index % colors.length]}"><title>${esc(metricLabel(row))}: ${esc(value)}</title></circle>`;
    }).join("");
    return `<svg class="data-chart data-scatter" viewBox="0 0 100 100" preserveAspectRatio="none">${points}</svg>`;
  }

  function renderLine(rows) {
    const values = rows.slice(0, 24).map(metricValue);
    const max = Math.max(...values, 1);
    const points = values.map((value, index) => {
      const x = values.length <= 1 ? 50 : 6 + (index / Math.max(values.length - 1, 1)) * 88;
      const y = 92 - (value / max) * 82;
      return `${x},${y}`;
    }).join(" ");
    return `<svg class="data-chart data-line" viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="#5b43d6" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>`;
  }

  async function init() {
    const select = document.getElementById("dataDashboardRole");
    const refresh = document.getElementById("refreshDataDashboard");
    if (!select || !refresh) return;

    const roleId = await loadRoles();
    if (roleId) await loadDashboard(roleId);

    select.addEventListener("change", () => loadDashboard(select.value));
    refresh.addEventListener("click", () => loadDashboard(select.value));
  }

  init();
}());

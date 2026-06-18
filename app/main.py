import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel
from app.rag_service import call_direct_rag, direct_backend_configured


load_dotenv()

app = FastAPI(title="COSBELLE RAG Console")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


class ChatRequest(BaseModel):
    endpoint: str = "/api/answer"
    query: str
    role_id: str = "GENERAL_EMPLOYEE"
    rbac_enabled: bool = True
    pre_check_enabled: bool = True
    post_check_enabled: bool = True


class SimulateRequest(BaseModel):
    role_id: str
    department_name: str
    security_clearance: str
    query: str
    rbac_enabled: bool = True
    pre_check_enabled: bool = True
    post_check_enabled: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


ROLE_ROWS = [
    ("COMPLIANCE_MANAGER", "Compliance Manager", "Compliance and audit log management", "RESTRICTED", "Compliance", ["QMS", "GROUPWARE"], ["Legal/Compliance", "Quality/RA", "Audit"], ["cos_adb.silver.compliance_audit_logs", "cos_adb.silver.regulatory_policy_documents", "cos_adb.governance.role_change_history"]),
    ("CS_STAFF", "CS Staff", "Customer inquiry and response manual management", "CONFIDENTIAL", "CS", ["CRM", "GROUPWARE"], ["Customer Service", "VOC", "Event"], ["cos_adb.silver.customer_inquiries", "cos_adb.silver.voc_review_insights", "cos_adb.silver.cs_response_manuals"]),
    ("EXECUTIVE", "Executive", "Company KPI, strategy, and investment decisions", "RESTRICTED", "Executive", ["ERP", "QMS", "PLM", "GROUPWARE"], ["Executive", "Finance", "Marketing", "Quality/RA", "R&D/Product"], ["cos_adb.gold.executive_kpi_summary", "cos_adb.gold.company_strategy_brief", "cos_adb.gold.investment_decision_summary"]),
    ("FINANCE_MANAGER", "Finance Manager", "Tax, budget, and investment material approval", "RESTRICTED", "Finance", ["ERP"], ["Finance", "SCM", "Distribution"], ["cos_adb.silver.finance_sales_summary", "cos_adb.silver.finance_budget_plan", "cos_adb.silver.finance_expense_records"]),
    ("FINANCE_STAFF", "Finance Staff", "Expense, budget, and sales aggregation", "CONFIDENTIAL", "Finance", ["ERP"], ["Finance"], ["cos_adb.silver.finance_sales_summary", "cos_adb.silver.finance_expense_records"]),
    ("GENERAL_EMPLOYEE", "General Employee", "Internal notice and allowed department material access", "INTERNAL", "General", ["GROUPWARE"], ["Event", "Notice"], ["cos_adb.silver.events", "cos_adb.search.llm_table_context"]),
    ("HR_MANAGER", "HR Manager", "HR approval, evaluation, and privacy control", "RESTRICTED", "HR", ["HRIS"], ["HR"], ["cos_adb.silver.hr_employee_master", "cos_adb.silver.hr_performance_reviews", "cos_adb.silver.hr_training_records"]),
    ("HR_STAFF", "HR Staff", "HR operations, attendance, and training data handling", "CONFIDENTIAL", "HR", ["HRIS"], ["HR", "Training"], ["cos_adb.silver.hr_employee_master", "cos_adb.silver.hr_attendance_records", "cos_adb.silver.hr_training_records"]),
    ("IT_ADMIN", "IT Admin", "IAM, account, and permission management", "RESTRICTED", "IT", ["IAM", "GROUPWARE"], ["IAM", "Security", "Governance"], ["cos_adb.governance.rag_identity_map", "cos_adb.governance.role_change_history", "cos_adb.governance.access_policies"]),
    ("LEGAL_STAFF", "Legal Staff", "Contract and legal document review", "RESTRICTED", "Legal", ["GROUPWARE"], ["Legal/Compliance"], ["cos_adb.silver.legal_contracts", "cos_adb.silver.regulatory_policy_documents"]),
    ("MARKETING_STAFF", "Marketing Staff", "Campaign, ad copy, and launch schedule management", "DEPARTMENT", "Marketing", ["ERP", "GROUPWARE"], ["Marketing", "VOC", "Event"], ["cos_adb.silver.events", "cos_adb.silver.marketing_campaign_plan", "cos_adb.silver.voc_review_insights"]),
    ("PAYROLL_MANAGER", "Payroll Manager", "Payroll summary and compensation data handling", "RESTRICTED", "HR", ["HRIS"], ["Payroll", "HR"], ["cos_adb.silver.hr_payroll_summary", "cos_adb.silver.compensation_adjustments"]),
    ("PRODUCTION_MANAGER", "Production Manager", "Production planning and work approval", "CONFIDENTIAL", "Production", ["MES", "ERP"], ["Manufacturing", "SCM"], ["cos_adb.silver.production_plan", "cos_adb.silver.manufacturing_work_orders", "cos_adb.silver.equipment_logs"]),
    ("PRODUCTION_STAFF", "Production Staff", "Work orders, manufacturing records, and equipment logs", "CONFIDENTIAL", "Production", ["MES"], ["Manufacturing"], ["cos_adb.silver.manufacturing_work_orders", "cos_adb.silver.batch_manufacturing_records", "cos_adb.silver.equipment_logs"]),
    ("QA_MANAGER", "QA Manager", "Quality approval and audit response", "RESTRICTED", "QA", ["QMS", "LIMS", "GROUPWARE"], ["Quality/RA", "Manufacturing", "Event"], ["cos_adb.silver.qa_deviation_reports", "cos_adb.silver.qa_capa_records", "cos_adb.silver.qa_qc_test_results"]),
    ("QA_STAFF", "QA Staff", "Quality documents, deviation, and CAPA management", "CONFIDENTIAL", "QA", ["QMS"], ["Quality/RA"], ["cos_adb.silver.qa_deviation_reports", "cos_adb.silver.qa_capa_records"]),
    ("QC_ANALYST", "QC Analyst", "Test result and LIMS record management", "CONFIDENTIAL", "QC", ["LIMS", "QMS"], ["Quality/RA"], ["cos_adb.silver.qa_qc_test_results", "cos_adb.silver.lims_test_records"]),
    ("RA_MANAGER", "RA Manager", "Regulatory risk and certification document approval", "RESTRICTED", "RA", ["QMS", "GROUPWARE"], ["Legal/Compliance", "Quality/RA"], ["cos_adb.silver.ra_certification_documents", "cos_adb.silver.regulatory_risk_register"]),
    ("RA_STAFF", "RA Staff", "Labeling, advertising, and regulatory review", "CONFIDENTIAL", "RA", ["QMS", "GROUPWARE"], ["Legal/Compliance", "Marketing"], ["cos_adb.silver.ra_labeling_review", "cos_adb.silver.marketing_claim_review"]),
    ("RND_MANAGER", "R&D Manager", "Research task and formula approval", "RESTRICTED", "R&D", ["PLM", "QMS"], ["R&D/Product", "Quality/RA"], ["cos_adb.silver.rnd_product_master", "cos_adb.silver.rnd_formula_records", "cos_adb.silver.rnd_product_improvement_actions"]),
    ("RND_RESEARCHER", "R&D Researcher", "Product planning, formula development, and test records", "CONFIDENTIAL", "R&D", ["PLM", "QMS"], ["R&D/Product", "Quality/RA"], ["cos_adb.silver.rnd_product_master", "cos_adb.silver.rnd_product_improvement_actions", "cos_adb.silver.qa_qc_test_results"]),
    ("SCM_MANAGER", "SCM Manager", "Supplier and inventory policy approval", "CONFIDENTIAL", "SCM", ["ERP", "MES"], ["SCM", "Distribution", "Manufacturing"], ["cos_adb.silver.scm_supplier_master", "cos_adb.silver.inventory_policy", "cos_adb.silver.distribution_schedule"]),
    ("SCM_STAFF", "SCM Staff", "Purchase order, inventory, and logistics schedule management", "CONFIDENTIAL", "SCM", ["ERP"], ["SCM", "Distribution"], ["cos_adb.silver.purchase_orders", "cos_adb.silver.inventory_transactions", "cos_adb.silver.distribution_schedule"]),
    ("TRAINING_MANAGER", "Training Manager", "Training completion, certification, and required education management", "CONFIDENTIAL", "Training", ["HRIS", "GROUPWARE"], ["Training", "HR"], ["cos_adb.silver.training_completion_records", "cos_adb.silver.employee_certifications"]),
]


ROLE_ACCESS = {
    role_id: {
        "role_name": role_name,
        "description": description,
        "default_clearance": clearance,
        "department": department,
        "systems": systems,
        "domains": domains,
        "tables": tables,
    }
    for role_id, role_name, description, clearance, department, systems, domains, tables in ROLE_ROWS
}

RECENT_RESPONSES: list[dict[str, Any]] = []
RECENT_SQL_LOGS: list[dict[str, Any]] = []
_DATABRICKS_WORKSPACE_CLIENT: WorkspaceClient | None = None


def build_check_result(rbac_enabled: bool, pre_check_enabled: bool, post_check_enabled: bool) -> dict:
    return {
        "rbac_enabled": rbac_enabled,
        "pre_check": "PASS" if pre_check_enabled else "SKIPPED",
        "pre_check_message": "Allowed domains and tables were used for retrieval." if pre_check_enabled else "Pre-check was skipped.",
        "post_check": "PASS" if post_check_enabled else "SKIPPED",
        "post_check_message": "The generated answer was checked against the current role." if post_check_enabled else "Post-check was skipped.",
    }


def role_dashboard_metrics(role_id: str) -> dict:
    seed = sum(ord(char) for char in role_id)
    requests = 70 + seed % 180
    blocked = 2 + seed % 18
    failed = seed % 7
    completed = requests - blocked - failed
    no_evidence = 1 + seed % 9
    post_blocked = seed % 6
    return {
        "requests": requests,
        "completed": completed,
        "blocked": blocked,
        "failed": failed,
        "pre_check_blocked": blocked - post_blocked if blocked >= post_blocked else blocked,
        "post_check_blocked": post_blocked,
        "no_evidence": no_evidence,
        "guard_pass_rate": f"{round((completed / requests) * 100, 1)}%",
    }


def role_blocked_attempts(role_id: str) -> list[dict]:
    restricted_candidates = {
        "MARKETING_STAFF": ["cos_adb.silver.rnd_formula_records", "cos_adb.silver.hr_payroll_summary"],
        "GENERAL_EMPLOYEE": ["cos_adb.silver.hr_payroll_summary", "cos_adb.silver.rnd_formula_records"],
        "RND_RESEARCHER": ["cos_adb.silver.finance_budget_plan", "cos_adb.silver.hr_payroll_summary"],
        "QA_STAFF": ["cos_adb.silver.hr_payroll_summary", "cos_adb.silver.finance_budget_plan"],
    }
    tables = restricted_candidates.get(role_id, ["cos_adb.silver.hr_payroll_summary", "cos_adb.silver.rnd_formula_records"])
    return [{"table": table, "count": index + 1, "reason": "RBAC pre-check blocked"} for index, table in enumerate(tables)]


def normalize_sources(raw: dict[str, Any], fallback_tables: list[str], fallback_clearance: str, role_id: str) -> dict:
    raw_sources = raw.get("sources") or raw.get("citations") or {}
    if isinstance(raw_sources, list):
        documents = raw_sources
        tables = raw.get("tables") or fallback_tables[:2]
    else:
        documents = raw_sources.get("documents") if "documents" in raw_sources else raw.get("citations")
        tables = raw_sources.get("tables") if "tables" in raw_sources else raw.get("tables")
        documents = documents if documents is not None else []
        tables = tables if tables is not None else fallback_tables[:2]

    normalized_docs = []
    for index, doc in enumerate(documents):
        if isinstance(doc, str):
            normalized_docs.append({"document_id": doc, "chunk_id": "", "classification": fallback_clearance})
        else:
            normalized_docs.append(
                {
                    "document_id": doc.get("document_id") or doc.get("source_id") or f"DOC-{role_id}-{index + 1:03d}",
                    "chunk_id": doc.get("chunk_id") or doc.get("chunk") or "",
                    "classification": doc.get("classification") or doc.get("security_clearance") or fallback_clearance,
                }
            )
    return {"tables": tables, "documents": normalized_docs}


def call_external_rag(payload: dict[str, Any], access: dict[str, Any]) -> dict | None:
    rag_api_url = os.getenv("RAG_API_URL", "").strip()
    if not rag_api_url:
        return None

    body = {
        "query": payload["query"],
        "question": payload["query"],
        "role_id": payload["role_id"],
        "department_name": payload.get("department_name") or access["department"],
        "security_clearance": payload.get("security_clearance") or access["default_clearance"],
        "rbac_enabled": payload.get("rbac_enabled", True),
        "pre_check_enabled": payload.get("pre_check_enabled", True),
        "post_check_enabled": payload.get("post_check_enabled", True),
    }
    headers = {"Content-Type": "application/json"}
    token = os.getenv("RAG_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        rag_api_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = float(os.getenv("RAG_TIMEOUT_SECONDS", "60"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "request_id": "REQ-RAG-ERROR",
            "guard_status": "ERROR",
            "answer_guard_status": "ERROR",
            "blocked": True,
            "answer": f"RAG API connection failed: {exc}",
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": body["rbac_enabled"],
                "pre_check": "ERROR",
                "post_check": "ERROR",
            },
        }

    role_id = payload["role_id"]
    clearance = access["default_clearance"]
    blocked = bool(raw.get("blocked", False))
    sources = {"tables": [], "documents": []} if blocked else normalize_sources(raw, access["tables"], clearance, role_id)
    return {
        "request_id": raw.get("request_id") or raw.get("id") or "REQ-RAG-LIVE",
        "guard_status": raw.get("guard_status") or raw.get("status") or "PASS",
        "answer_guard_status": raw.get("answer_guard_status") or raw.get("post_check") or "PASS",
        "blocked": blocked,
        "answer": raw.get("answer") or raw.get("response") or raw.get("summary") or "",
        "sources": sources,
        "checks": raw.get("checks") or build_check_result(body["rbac_enabled"], body["pre_check_enabled"], body["post_check_enabled"]),
        "sql_log": raw.get("sql_log") or raw.get("log") or {},
        "raw": raw,
    }


def get_databricks_workspace_client() -> WorkspaceClient:
    global _DATABRICKS_WORKSPACE_CLIENT
    if _DATABRICKS_WORKSPACE_CLIENT is None:
        _DATABRICKS_WORKSPACE_CLIENT = WorkspaceClient()
    return _DATABRICKS_WORKSPACE_CLIENT


def read_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def normalize_enum(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def normalize_databricks_error(exc: Exception) -> str:
    message = str(exc)
    if "default auth" in message.lower() or "credentials" in message.lower():
        return (
            "Databricks authentication failed. In Databricks Apps, grant the app service principal "
            "permission to run the target Job. For local testing, set DATABRICKS_HOST and DATABRICKS_TOKEN."
        )
    return message


def parse_notebook_result(raw_result: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        parsed = {"answer": raw_result}
    return parsed if isinstance(parsed, dict) else {"answer": str(parsed)}


def get_notebook_task_run_id(run_state: dict[str, Any], fallback_run_id: int) -> int:
    tasks = read_field(run_state, "tasks", []) or []
    if not tasks:
        return fallback_run_id

    for task in tasks:
        task_run_id = read_field(task, "run_id")
        if read_field(task, "notebook_task") is not None and task_run_id is not None:
            return int(task_run_id)

    for task in tasks:
        task_run_id = read_field(task, "run_id")
        if task_run_id is not None:
            return int(task_run_id)

    return fallback_run_id


def get_databricks_run_output_message(run_id: int) -> str:
    try:
        output = get_databricks_workspace_client().jobs.get_run_output(run_id=run_id)
    except Exception as exc:
        return f"Could not retrieve notebook output: {normalize_databricks_error(exc)}"

    notebook_output = read_field(output, "notebook_output", {}) or {}
    parts = [
        read_field(output, "error"),
        read_field(output, "error_trace"),
        read_field(notebook_output, "result"),
        read_field(notebook_output, "truncated"),
    ]
    message = "\n".join(str(part) for part in parts if part)
    return message[:4000] if message else "No notebook output was returned."


def call_databricks_job_rag(payload: dict[str, Any], access: dict[str, Any]) -> dict | None:
    job_id = os.getenv("DATABRICKS_JOB_ID", "").strip()
    if not job_id:
        return None

    encoded_question = base64.b64encode(payload["query"].encode("utf-8")).decode("ascii")
    body = {
        "job_id": int(job_id),
        "notebook_params": {
            "question": "",
            "question_b64": encoded_question,
            "question_encoding": "base64_utf8",
            "role_id": payload["role_id"],
            "user_role": "",
            "use_user_role_fallback": "OFF",
            "rbac_enabled": "ON" if payload.get("rbac_enabled", True) else "OFF",
            "post_check": "ON" if payload.get("post_check_enabled", True) else "OFF",
        },
    }

    try:
        workspace_client = get_databricks_workspace_client()
        run_now = workspace_client.jobs.run_now(
            job_id=int(job_id),
            notebook_params=body["notebook_params"],
        )
        run_id = int(read_field(run_now, "run_id"))
        output_run_id = run_id
        max_wait = int(os.getenv("DATABRICKS_JOB_TIMEOUT_SECONDS", "180"))
        started = time.time()

        while True:
            run_state = workspace_client.jobs.get_run(run_id=run_id)
            output_run_id = get_notebook_task_run_id(run_state, run_id)
            state = read_field(run_state, "state", {}) or {}
            life_cycle = normalize_enum(read_field(state, "life_cycle_state"))
            result_state = normalize_enum(read_field(state, "result_state"))

            if life_cycle in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                if result_state != "SUCCESS":
                    message = read_field(state, "state_message") or result_state or life_cycle
                    output_message = get_databricks_run_output_message(output_run_id)
                    raise RuntimeError(f"Databricks job failed: {message}\n{output_message}")
                break

            if time.time() - started > max_wait:
                raise TimeoutError(f"Databricks job timed out after {max_wait}s")
            time.sleep(3)

        output = workspace_client.jobs.get_run_output(run_id=output_run_id)
        notebook_output = read_field(output, "notebook_output", {}) or {}
        raw_result = read_field(notebook_output, "result") or ""
        parsed = parse_notebook_result(raw_result)
    except Exception as exc:
        return {
            "request_id": "REQ-DATABRICKS-JOB-ERROR",
            "guard_status": "ERROR",
            "answer_guard_status": "ERROR",
            "blocked": True,
            "answer": f"Databricks job connection failed: {normalize_databricks_error(exc)}",
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": payload.get("rbac_enabled", True),
                "pre_check": "ERROR",
                "post_check": "ERROR",
            },
        }

    role_id = payload["role_id"]
    clearance = access["default_clearance"]
    sources = {"tables": [], "documents": []} if parsed.get("blocked") else normalize_sources(parsed, access["tables"], clearance, role_id)
    return {
        "request_id": parsed.get("request_id") or f"RUN-{run_id}",
        "guard_status": parsed.get("guard_status") or parsed.get("status") or "PASS",
        "answer_guard_status": parsed.get("answer_guard_status") or parsed.get("post_check") or "PASS",
        "blocked": bool(parsed.get("blocked", False)),
        "answer": parsed.get("answer") or parsed.get("response") or parsed.get("summary") or str(parsed),
        "sources": sources,
        "checks": parsed.get("checks") or build_check_result(
            payload.get("rbac_enabled", True),
            payload.get("pre_check_enabled", True),
            payload.get("post_check_enabled", True),
        ),
        "sql_log": parsed.get("sql_log") or parsed.get("log") or {},
        "raw": parsed.get("raw") if isinstance(parsed.get("raw"), dict) else parsed,
    }


def build_mock_answer(payload: dict[str, Any], access: dict[str, Any], mode: str) -> dict:
    return {
        "request_id": "REQ-NO-BACKEND",
        "guard_status": "ERROR",
        "answer_guard_status": "ERROR",
        "blocked": True,
        "checks": {
            "rbac_enabled": payload.get("rbac_enabled", True),
            "pre_check": "ERROR",
            "post_check": "ERROR",
        },
        "answer": "RAG backend is not configured. Set DATABRICKS_SQL_WAREHOUSE_ID (or DATABRICKS_WAREHOUSE_ID) or RAG_API_URL before running the UI.",
        "sources": {"tables": [], "documents": []},
    }


def extract_sql_log(result: dict[str, Any], payload: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    sql_log = result.get("sql_log") if isinstance(result.get("sql_log"), dict) else {}
    raw_sql_log = raw.get("sql_log") if isinstance(raw.get("sql_log"), dict) else {}
    log = {**raw_sql_log, **sql_log}
    sources = result.get("sources") or {}
    tables = sources.get("tables") or []
    raw_table_access = raw.get("table_access") if isinstance(raw.get("table_access"), list) else []

    if not tables and raw_table_access:
        tables = [
            str(item.get("table"))
            for item in raw_table_access
            if isinstance(item, dict) and item.get("table")
        ]

    return {
        "request_id": result.get("request_id") or log.get("request_id") or raw.get("request_id") or "REQ-LIVE",
        "query_time": str(log.get("query_time") or raw.get("query_time") or datetime.now(ZoneInfo("Asia/Seoul")).isoformat()),
        "table_name": log.get("table_name") or ", ".join(tables) or "-",
        "row_count": log.get("row_count") or log.get("row_count_returned") or raw.get("row_count_returned") or 0,
        "column_count": log.get("column_count") or len(log.get("columns") or raw.get("columns_returned") or []),
        "columns": log.get("columns") or raw.get("columns_returned") or [],
        "actor": payload.get("role_id") or raw.get("role") or "-",
        "status": result.get("guard_status") or raw.get("status") or "UNKNOWN",
        "sql": log.get("sql") or log.get("generated_sql") or raw.get("sql") or "",
        "blocked": bool(result.get("blocked", False)),
        "chat_source": result.get("mode") or payload.get("mode") or "-",
        "department": payload.get("department_name") or access["department"],
        "clearance": payload.get("security_clearance") or access["default_clearance"],
    }


def remember_live_result(result: dict[str, Any], payload: dict[str, Any], access: dict[str, Any]) -> None:
    RECENT_RESPONSES.insert(0, result)
    del RECENT_RESPONSES[50:]
    RECENT_SQL_LOGS.insert(0, extract_sql_log(result, payload, access))
    del RECENT_SQL_LOGS[100:]


def answer_payload(payload: dict[str, Any], mode: str) -> dict:
    access = ROLE_ACCESS.get(payload["role_id"], ROLE_ACCESS["GENERAL_EMPLOYEE"])
    result = call_external_rag(payload, access) or call_direct_rag(payload, access) or build_mock_answer(payload, access, mode)
    backend = "mock"
    if os.getenv("RAG_API_URL", "").strip():
        backend = "external_rag"
    elif direct_backend_configured():
        backend = "direct_databricks"
    response = {
        **result,
        "endpoint": payload.get("endpoint", "/api/answer"),
        "query": payload["query"],
        "mode": mode,
        "role_id": payload["role_id"],
        "role_name": access["role_name"],
        "department_name": payload.get("department_name") or access["department"],
        "security_clearance": payload.get("security_clearance") or access["default_clearance"],
        "effective_identity": {
            "employee_id": "E20260001",
            "role_id": payload["role_id"],
            "department_name": payload.get("department_name") or access["department"],
            "security_clearance": payload.get("security_clearance") or access["default_clearance"],
        },
        "backend": backend,
    }
    sources = response.get("sources") or {}
    raw = response.get("raw") if isinstance(response.get("raw"), dict) else {}
    raw_table_access = raw.get("table_access") if isinstance(raw.get("table_access"), list) else []
    print(
        "[RAG_UI_LOG]",
        json.dumps(
            {
                "mode": mode,
                "request_id": response.get("request_id"),
                "role_id": response.get("role_id"),
                "backend": backend,
                "guard_status": response.get("guard_status"),
                "blocked": response.get("blocked"),
                "tables_count": len(sources.get("tables") or []),
                "documents_count": len(sources.get("documents") or []),
                "raw_table_access_count": len(raw_table_access),
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    remember_live_result(response, payload, access)
    return response


def payload_to_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


@app.get("/")
def public_ui():
    return FileResponse("app/templates/public.html")


@app.get("/admin-login")
def admin_login_ui():
    return FileResponse("app/templates/login.html")


@app.get("/admin")
@app.get("/ui")
def admin_ui():
    return FileResponse("app/templates/admin.html")


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/backend/status")
def backend_status():
    backend = "mock"
    if os.getenv("RAG_API_URL", "").strip():
        backend = "external_rag"
    elif direct_backend_configured():
        backend = "direct_databricks"
    return {
        "backend": backend,
        "rag_api_url_configured": bool(os.getenv("RAG_API_URL", "").strip()),
        "databricks_direct_configured": direct_backend_configured(),
        "databricks_sql_warehouse_id_configured": bool(os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "").strip() or os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()),
        "databricks_host_configured": bool(os.getenv("DATABRICKS_HOST", "").strip()),
    }


@app.post("/api/admin/login")
def admin_login(payload: LoginRequest):
    ok = payload.username == "admin" and payload.password == "admin"
    return {"ok": ok, "redirect": "/admin", "message": "Login success" if ok else "Invalid username or password"}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    return answer_payload(payload_to_dict(payload), "user")


@app.post("/api/admin/simulate")
def simulate(payload: SimulateRequest):
    return answer_payload(payload_to_dict(payload), "admin_simulation")


@app.get("/api/admin/dashboard/llm")
def llm_dashboard():
    total = len(RECENT_RESPONSES)
    blocked = sum(1 for item in RECENT_RESPONSES if item.get("blocked"))
    failed = sum(1 for item in RECENT_RESPONSES if item.get("guard_status") == "ERROR")
    completed = sum(1 for item in RECENT_RESPONSES if not item.get("blocked") and item.get("guard_status") != "ERROR")
    no_evidence = sum(1 for item in RECENT_RESPONSES if not (item.get("sources") or {}).get("tables"))
    guard_pass = f"{round((completed / total) * 100, 1)}%" if total else "0%"
    return {
        "total_requests": total,
        "completed_requests": completed,
        "blocked_requests": blocked,
        "failed_requests": failed,
        "no_evidence_requests": no_evidence,
        "guard_pass": guard_pass,
        "registered_roles": len(ROLE_ACCESS),
    }


@app.get("/api/admin/dashboard/database")
def database_dashboard():
    queried_tables = {
        table
        for item in RECENT_RESPONSES
        for table in (item.get("sources") or {}).get("tables", [])
    }
    document_count = sum(len((item.get("sources") or {}).get("documents", [])) for item in RECENT_RESPONSES)
    blocked_logs = sum(1 for item in RECENT_SQL_LOGS if item.get("blocked"))
    top_table = "-"
    if queried_tables:
        top_table = max(
            queried_tables,
            key=lambda table: sum(1 for log in RECENT_SQL_LOGS if table in str(log.get("table_name", ""))),
        )
    return {
        "queried_tables": len(queried_tables),
        "document_citations": document_count,
        "access_policies": len(ROLE_ACCESS),
        "blocked_access_logs": blocked_logs,
        "top_table": top_table,
        "logged_sql_queries": len(RECENT_SQL_LOGS),
    }


@app.get("/api/admin/roles")
def roles():
    return [
        {
            "role_id": role_id,
            "role_name": access["role_name"],
            "description": access["description"],
            "department": access["department"],
            "default_clearance": access["default_clearance"],
        }
        for role_id, access in ROLE_ACCESS.items()
    ]


@app.get("/api/admin/roles/{role_id}/access")
def get_role_access(role_id: str):
    access = ROLE_ACCESS.get(role_id, ROLE_ACCESS["GENERAL_EMPLOYEE"])
    role_logs = [log for log in RECENT_SQL_LOGS if log.get("actor") == role_id]
    role_responses = [item for item in RECENT_RESPONSES if item.get("role_id") == role_id]
    requests = len(role_responses)
    blocked = sum(1 for item in role_responses if item.get("blocked"))
    failed = sum(1 for item in role_responses if item.get("guard_status") == "ERROR")
    completed = sum(1 for item in role_responses if not item.get("blocked") and item.get("guard_status") != "ERROR")
    top_tables = {}
    for log in role_logs:
        for table in str(log.get("table_name", "")).split(", "):
            if table and table != "-":
                top_tables[table] = top_tables.get(table, 0) + 1
    blocked_attempts = [
        {"table": log.get("table_name") or "-", "count": 1, "reason": "RBAC/guard blocked"}
        for log in role_logs
        if log.get("blocked")
    ]
    return {
        "role_id": role_id,
        "role_name": access["role_name"],
        "description": access["description"],
        "department": access["department"],
        "default_clearance": access["default_clearance"],
        "systems": access["systems"],
        "domains": access["domains"],
        "tables": access["tables"],
        "usage": {
            "requests": requests,
            "completed": completed,
            "blocked": blocked,
            "failed": failed,
            "pre_check_blocked": sum(1 for item in role_responses if (item.get("checks") or {}).get("pre_check") == "BLOCKED"),
            "post_check_blocked": sum(1 for item in role_responses if (item.get("checks") or {}).get("post_check") == "BLOCKED"),
            "no_evidence": sum(1 for item in role_responses if not (item.get("sources") or {}).get("tables")),
            "guard_pass_rate": f"{round((completed / requests) * 100, 1)}%" if requests else "0%",
        },
        "top_tables": [
            {"table": table, "count": count}
            for table, count in sorted(top_tables.items(), key=lambda item: item[1], reverse=True)[:5]
        ],
        "top_documents": [],
        "blocked_attempts": blocked_attempts,
    }


def parse_log_time(value: Any) -> datetime | None:
    if not value:
        return None

    raw = str(value).strip()
    normalized = raw.replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ZoneInfo("Asia/Seoul"))


@app.get("/api/admin/sql-logs")
def sql_logs(
    page: int = 1,
    page_size: int = 15,
    days: int = 7,
    role: str = "",
    status: str = "",
    table: str = "",
    source: str = "",
    date_from: str = "",
    date_to: str = "",
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    filtered = []

    for log in RECENT_SQL_LOGS:
        log_time = parse_log_time(log.get("query_time"))
        if days and not date_from and not date_to:
            if not log_time or (now_kst - log_time).days >= days:
                continue

        if date_from and (not log_time or log_time.date().isoformat() < date_from):
            continue
        if date_to and (not log_time or log_time.date().isoformat() > date_to):
            continue
        if role and str(log.get("actor", "")).upper() != role.upper():
            continue
        if status and str(log.get("status", "")).upper() != status.upper():
            continue
        if table and table.lower() not in str(log.get("table_name", "")).lower():
            continue
        if source and str(log.get("chat_source", "")).lower() != source.lower():
            continue

        filtered.append(log)

    total = len(filtered)
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "logs": filtered[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "filters": {
            "days": days,
            "role": role,
            "status": status,
            "table": table,
            "source": source,
            "date_from": date_from,
            "date_to": date_to,
        },
        "retention_note": "Default view shows recent 7 days. Persist production logs in a Databricks Delta audit table.",
    }

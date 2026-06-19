import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from databricks.sdk import WorkspaceClient


CATALOG = os.getenv("RAG_SQL_CATALOG", "cos_adb")
LOG_TABLE = os.getenv("RAG_SQL_LOG_TABLE", f"{CATALOG}.governance.rag_sql_query_logs")
SQL_TIMEOUT_SECONDS = int(os.getenv("DIRECT_SQL_TIMEOUT_SECONDS", "45"))
MAX_LOG_ROWS = int(os.getenv("RAG_SQL_LOG_MAX_ROWS", "5000"))

_CLIENT: WorkspaceClient | None = None


def _client() -> WorkspaceClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = WorkspaceClient()
    return _CLIENT


def _read_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _normalize_enum(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _warehouse_id() -> str:
    return os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "").strip() or os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()


def direct_backend_configured() -> bool:
    return bool(_warehouse_id())


def _statement_rows(statement_obj: Any) -> tuple[list[str], list[dict[str, Any]]]:
    result = _read_field(statement_obj, "result", {}) or {}
    manifest = _read_field(statement_obj, "manifest", {}) or _read_field(result, "manifest", {}) or {}
    schema = _read_field(manifest, "schema", {}) or {}
    cols_meta = _read_field(schema, "columns", []) or []
    columns = [str(_read_field(col, "name", "")) for col in cols_meta]

    rows = _read_field(result, "data_array", []) or []
    if not columns and rows and isinstance(rows[0], (list, tuple)):
        columns = [f"col_{idx + 1}" for idx in range(len(rows[0]))]

    dict_rows: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            dict_rows.append(row)
        elif isinstance(row, (list, tuple)):
            dict_rows.append({columns[idx]: row[idx] for idx in range(min(len(columns), len(row)))})
        else:
            dict_rows.append({"value": row})
    return columns, dict_rows


def _execute_sql(statement_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    warehouse_id = _warehouse_id()
    if not warehouse_id:
        raise RuntimeError("DATABRICKS_SQL_WAREHOUSE_ID is not configured")

    client = _client()
    stmt = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement_text,
        wait_timeout="30s",
        row_limit=MAX_LOG_ROWS,
    )

    statement_id = _read_field(stmt, "statement_id")
    started = time.time()

    while True:
        status_obj = _read_field(stmt, "status", {}) or {}
        state = (_normalize_enum(_read_field(status_obj, "state")) or "").upper()

        if state == "SUCCEEDED":
            return _statement_rows(stmt)
        if state in {"FAILED", "CANCELED", "CLOSED"}:
            err = _read_field(status_obj, "error", {}) or {}
            message = _read_field(err, "message", None) or _read_field(status_obj, "state_message", None) or state
            raise RuntimeError(f"SQL execution failed: {message}")

        if not statement_id:
            raise RuntimeError("Statement execution did not return statement_id")
        if time.time() - started > SQL_TIMEOUT_SECONDS:
            raise TimeoutError(f"SQL execution timed out after {SQL_TIMEOUT_SECONDS}s")

        time.sleep(0.7)
        stmt = client.statement_execution.get_statement(statement_id=statement_id)


def _query_dicts(sql: str) -> list[dict[str, Any]]:
    _, rows = _execute_sql(sql)
    return rows


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value in (None, ""):
        return []
    return [value]


def _as_text(value: Any, default: str = "-") -> str:
    if value in (None, ""):
        return default
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item not in (None, "")) or default
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    tables_accessed = _as_list(row.get("tables_accessed"))
    columns_returned = _as_list(row.get("columns_returned"))
    query_time = row.get("query_time") or row.get("created_at") or _kst_now_iso()
    execution_status = _as_text(row.get("execution_status") or row.get("status") or "UNKNOWN", "UNKNOWN")
    user_question = _as_text(row.get("user_question") or row.get("question"), "-")
    generated_sql = _as_text(row.get("generated_sql") or row.get("sql"), "")
    success_reason = _as_text(row.get("success_reason"), "")
    failure_reason = _as_text(row.get("failure_reason"), "")
    error_message = _as_text(row.get("error_message") or row.get("detail"), "")
    permission_check = _as_text(row.get("permission_check") or row.get("chat_source") or row.get("source"), "-")

    return {
        "request_id": _as_text(row.get("request_id") or row.get("log_id") or row.get("query_id"), "REQ-LIVE"),
        "query_time": str(query_time),
        "question": user_question,
        "table_name": ", ".join(str(item) for item in tables_accessed) if tables_accessed else "-",
        "row_count": _as_int(row.get("row_count_returned") or row.get("row_count") or row.get("rows")),
        "column_count": _as_int(row.get("column_count"), len(columns_returned)) if columns_returned else _as_int(row.get("column_count")),
        "columns": columns_returned,
        "actor": _as_text(row.get("role_id") or row.get("user_id") or row.get("actor") or row.get("role"), "-"),
        "status": execution_status,
        "sql": generated_sql,
        "blocked": bool(row.get("blocked") or execution_status.upper() in {"BLOCKED", "DENIED", "ERROR", "FAILED", "FAILURE"}),
        "chat_source": permission_check,
        "department": _as_text(row.get("department_id") or row.get("department_name") or row.get("department"), "-"),
        "clearance": _as_text(row.get("clearance") or row.get("security_clearance"), "-"),
        "answer": success_reason or failure_reason or error_message,
        "raw": row,
    }


def _kst_now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("query_time") or ""), str(row.get("request_id") or ""))


def fetch_sql_logs(
    page: int = 1,
    page_size: int = 15,
    days: int = 7,
    role: str = "",
    status: str = "",
    table: str = "",
    source: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    warehouse_id = _warehouse_id()
    if not warehouse_id:
        return {"source": "unconfigured", "logs": []}

    rows = _query_dicts(
        f"""
        SELECT *
        FROM {LOG_TABLE}
        ORDER BY COALESCE(query_time, created_at) DESC
        LIMIT {MAX_LOG_ROWS}
        """
    )
    normalized = [_normalize_log_row(row) for row in rows]

    filtered = []
    for log in normalized:
        log_time = _parse_log_time(log.get("query_time"))
        if days and not date_from and not date_to:
            if not log_time or (datetime.now(ZoneInfo("Asia/Seoul")) - log_time).days >= days:
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
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "source": "databricks_table",
        "table": LOG_TABLE,
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
    }


def _parse_log_time(value: Any) -> datetime | None:
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
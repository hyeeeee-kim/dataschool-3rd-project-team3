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


def _column_names(table_fqn: str) -> list[str]:
    rows = _query_dicts(
        f"""
        SELECT column_name
        FROM {CATALOG}.information_schema.columns
        WHERE table_catalog = '{CATALOG}'
          AND table_schema = 'governance'
          AND table_name = 'rag_sql_query_logs'
        ORDER BY ordinal_position
        """
    )
    return [str(row.get("column_name", "")) for row in rows if row.get("column_name")]


def _pick_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        column = lowered.get(candidate.lower())
        if column:
            return column
    return None


def _first_value(row: dict[str, Any], candidates: list[str], default: Any = None) -> Any:
    for candidate in candidates:
        if candidate in row and row.get(candidate) not in (None, ""):
            return row.get(candidate)
    return default


def _normalize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    question = _first_value(row, ["question", "user_question", "query", "raw_question", "prompt"], "-")
    table_name = _first_value(row, ["table_name", "table", "source_table", "target_table"], "-")
    columns = row.get("columns") or row.get("column_names") or row.get("columns_returned") or []
    if isinstance(columns, str):
        columns = [item.strip() for item in columns.split(",") if item.strip()]
    elif not isinstance(columns, list):
        columns = []

    query_time = _first_value(row, ["query_time", "created_at", "timestamp", "event_time", "logged_at"], _kst_now_iso())

    return {
        "request_id": _first_value(row, ["request_id", "id", "query_id"], "REQ-LIVE"),
        "query_time": str(query_time),
        "question": str(question or "-"),
        "table_name": str(table_name or "-"),
        "row_count": int(_first_value(row, ["row_count", "row_count_returned", "rows"], 0) or 0),
        "column_count": int(_first_value(row, ["column_count"], len(columns)) or len(columns)),
        "columns": columns,
        "actor": str(_first_value(row, ["actor", "role_id", "user_id", "role"], "-") or "-"),
        "status": str(_first_value(row, ["status", "guard_status", "result_status"], "UNKNOWN") or "UNKNOWN"),
        "sql": str(_first_value(row, ["sql", "generated_sql", "statement_text"], "") or ""),
        "blocked": bool(row.get("blocked") or str(_first_value(row, ["status", "guard_status"], "")).upper() in {"BLOCKED", "DENIED", "ERROR"}),
        "chat_source": str(_first_value(row, ["chat_source", "source", "mode"], "-") or "-"),
        "department": str(_first_value(row, ["department", "department_name"], "-") or "-"),
        "clearance": str(_first_value(row, ["clearance", "security_clearance"], "-") or "-"),
        "answer": str(_first_value(row, ["answer", "response", "summary"], "") or ""),
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
    if not direct_backend_configured():
        return {"source": "unconfigured", "logs": []}

    try:
        _query_dicts(
            f"""
            SELECT 1
            FROM {CATALOG}.information_schema.tables
            WHERE table_schema = 'governance'
              AND table_name = 'rag_sql_query_logs'
            LIMIT 1
            """
        )
    except Exception:
        return {"source": "missing_table", "logs": []}

    columns = _column_names(LOG_TABLE)
    order_column = _pick_column(columns, ["query_time", "created_at", "timestamp", "event_time", "logged_at", "request_time"])
    order_sql = f"ORDER BY {order_column} DESC" if order_column else ""
    rows = _query_dicts(f"SELECT * FROM {LOG_TABLE} {order_sql} LIMIT {MAX_LOG_ROWS}")
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
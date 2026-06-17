import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any



def kst_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)


def extract_tables(output: dict[str, Any]) -> list[str]:
    sql = output.get("sql")
    if sql:
        pattern = r"(?i)\b(?:from|join)\s+([`\w\.]+)"
        tables = {
            value.replace("`", "").strip()
            for value in re.findall(pattern, sql)
            if value.replace("`", "").lower().startswith("cos_adb.")
        }
        if tables:
            return sorted(tables)

    return sorted(
        {
            item.get("table")
            for item in (output.get("table_access") or [])
            if isinstance(item, dict) and item.get("table")
        }
    )


# ---------------------------------------------------------------------------
# SQL helpers for safe literal formatting
# ---------------------------------------------------------------------------

def _s(val: Any) -> str:
    """Scalar → SQL string literal or NULL."""
    if val is None:
        return "NULL"
    return "'" + str(val).replace("'", "''") + "'"


def _ts(val: datetime | None) -> str:
    """datetime → CAST('...' AS TIMESTAMP) or NULL."""
    if val is None:
        return "NULL"
    return f"CAST('{val.strftime('%Y-%m-%d %H:%M:%S')}' AS TIMESTAMP)"


def _arr(vals: list[str] | None) -> str:
    """list[str] → ARRAY('a', 'b') literal."""
    if not vals:
        return "ARRAY()"
    items = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
    return f"ARRAY({items})"


def _int(val: Any) -> str:
    """int | None → SQL integer literal or NULL."""
    if val is None:
        return "NULL"
    return str(int(val))


# ---------------------------------------------------------------------------


def save_rag_log(log_table: str, output: dict[str, Any]) -> str | None:
    try:
        from .db_client import run_statement

        execution_status = output.get("execution_status")
        log_id = str(uuid.uuid4())
        now = kst_now()

        sql = f"""
        INSERT INTO {log_table} (
            log_id, request_id, query_time, user_question,
            generated_sql, tables_accessed, columns_returned, row_count_returned,
            execution_status, success_reason, failure_reason, error_message,
            query_runtime_ms, user_id, role_id, department_id,
            permission_check, created_at
        ) VALUES (
            {_s(log_id)},
            {_s(output.get('request_id'))},
            {_ts(output.get('query_time'))},
            {_s(output.get('question'))},
            {_s(output.get('sql'))},
            {_arr(extract_tables(output))},
            {_arr(output.get('columns_returned') or [])},
            {_int(output.get('row_count_returned'))},
            {_s(execution_status)},
            {_s(output.get('success_reason'))},
            {_s(output.get('failure_reason'))},
            {_s(output.get('detail') if execution_status == 'FAILED' else None)},
            {_int(output.get('query_runtime_ms'))},
            {_s(output.get('user_id'))},
            {_s(output.get('role'))},
            {_s(output.get('department_id'))},
            {_s(output.get('permission_check'))},
            {_ts(now)}
        )
        """
        run_statement(sql)
        print(f"[LOG SAVED] log_id={log_id}, status={execution_status}")
        return log_id
    except Exception as error:
        print(f"[LOG ERROR] {str(error)[:500]}")
        return None
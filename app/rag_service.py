import json
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole


CATALOG = os.getenv("RAG_SQL_CATALOG", "cos_adb")
LLM_MODEL = os.getenv("RAG_LLM_MODEL", "databricks-qwen3-next-80b-a3b-instruct")
VS_INDEX_NAME = os.getenv("RAG_VS_INDEX_NAME", "cos_adb.search.metadata_chunks_index")
SQL_TIMEOUT_SECONDS = int(os.getenv("DIRECT_SQL_TIMEOUT_SECONDS", "45"))

SYSTEM_TO_DOMAINS = {
    "HRIS": ["HR"],
    "PLM": ["R&D/Product"],
    "QMS": ["Quality/RA", "Legal/Compliance"],
    "MES": ["Manufacturing"],
    "LIMS": ["Quality/RA"],
    "ERP": ["Finance", "SCM", "Distribution", "Customer Service", "Marketing"],
    "GROUPWARE": ["Event", "VOC"],
    "IAM": ["Security/Governance", "Metadata/Governance"],
    "FILE_STORAGE": ["Legal/Compliance"],
}

UNIVERSAL_DOMAINS = ["Master/Governance", "Evaluation"]

PROMPT_SQL_GENERATION = """You are a Databricks SQL expert for '{catalog}' Unity Catalog.

## STRICT RULES (violations = failure)
1. Use ONLY tables from [Allowed Tables]. NO other tables exist.
2. Use ONLY columns shown in [Context]. NEVER invent column names.
3. [Context]의 table_id는 내부명입니다. SQL에는 [Table Name Mapping]의 실제 FQN을 사용하세요.
4. LIMIT 20 기본 추가.
5. Return ONLY a single ```sql ... ``` block. No explanation.

## Allowed Tables
{table_list}

## Table Name Mapping (context 내부명 -> 실제 FQN)
{table_id_mapping}

## Key Column Reference
- cos_adb.silver.events: event_id, event_type, product_id, product_name, batch_id, owner_employee_id, owner_name, affected_departments, start_date, quarter, season, business_cycle, campaign_period, status, business_impact
- 도메인 전용 테이블(qa_*, mfg_*, rnd_* 등): [Context] 컬럼목록 참고.
{error_section}"""

PROMPT_SQL_USER = """[Context]
{context}

[Question] {question}

주의: [Context]의 테이블/컬럼 정보를 반드시 참고. 컬럼명을 추측하지 마세요."""

PROMPT_SUMMARIZE_SYSTEM = """사용자 질문에 대해 SQL 결과 기반으로 한국어로 간결히 답변.
핵심 수치와 인사이트 강조. 표로 정리 가능하면 표 사용."""

PROMPT_SUMMARIZE_USER = """질문: {question}\nSQL:\n{sql}\n결과:\n{results}"""

POSTCHECK_SYSTEM = """당신은 보안 감사자입니다. 사용자의 역할, 허용된 테이블, SQL, 결과를 검토하세요:
- SQL이 허용 목록 외의 테이블을 참조하는지 확인.
- 결과가 제한된 도메인의 민감 데이터를 노출하는지 확인.
PASS 또는 FAIL: <사유> 로만 응답하세요."""

POSTCHECK_USER = """역할: {role}
허용된 테이블:
{allowed_tables}

생성된 SQL:
{sql}

실행 결과:
{results}

판정:"""

INTENT_SYSTEM = """Classify the user's question into exactly one category.
Respond with ONLY the category name, nothing else.

Categories:
- WORK: 데이터 조회, 수치/통계 요청, DB 테이블 관련, 보고서, 특정 기간/제품/직원 실적 질문
- CHAT: 일반 대화, 인사, 의견/조언 요청, 개념 설명, 업무 절차 질문, DB 불필요한 질문"""

INTENT_USER = "질문: {question}\n분류:"

CHAT_SYSTEM_PROMPT = """당신은 코스벨(Cosbelle) 화장품 제조기업의 사내 AI 어시스턴트입니다.

## 역할
- 친절하고 전문적으로 한국어로 답변합니다.
- 화장품 산업, 품질관리, 제조, R&D, 규제(RA) 등 도메인 지식을 활용합니다.
- 데이터 조회가 필요한 질문에는 \"/work 모드를 사용해주세요\"라고 안내합니다.

## 대화 스타일
- 간결하되 필요한 정보는 빠짐없이 전달
- 전문 용어는 설명을 덧붙여 이해를 도움
- 불확실한 정보는 명확히 표시"""

LLM_PARAMS = {
    "sql_generation": {"max_tokens": 512, "temperature": 0.0},
    "summarization": {"max_tokens": 1024, "temperature": 0.1},
}

MSG_ACCESS_DENIED = "[{role}] 역할로는 해당 질문에 관련된 데이터에 접근할 수 없습니다."

_CLIENT: WorkspaceClient | None = None
_CONVERSATION_MEMORY: deque[dict[str, str]] = deque(maxlen=20)


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


def _kst_now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _llm_call(system: str, user: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
    response = _client().serving_endpoints.query(
        name=LLM_MODEL,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
            ChatMessage(role=ChatMessageRole.USER, content=user),
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


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

    w = _client()
    stmt = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement_text,
        wait_timeout="30s",
        row_limit=1000,
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
        stmt = w.statement_execution.get_statement(statement_id=statement_id)


def _query_dicts(sql: str) -> list[dict[str, Any]]:
    _, rows = _execute_sql(sql)
    return rows


def _extract_sql(text: str) -> str:
    matched = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL)
    return matched.group(1).strip() if matched else text.strip()


def _search_metadata(query: str, top_k: int = 5, allowed_domains: list[str] | None = None) -> list[list[Any]]:
    kwargs: dict[str, Any] = {
        "index_name": VS_INDEX_NAME,
        "query_text": query,
        "num_results": top_k,
        "columns": ["source_type", "source_id", "chunk_text", "domain"],
    }
    if allowed_domains:
        kwargs["filters_json"] = json.dumps({"domain": allowed_domains})
    response = _client().vector_search_indexes.query_index(**kwargs)
    return response.result.data_array


def _build_context(results: list[list[Any]]) -> str:
    return "\n\n".join(f"--- [{item[0]}] {item[1]} ({item[3]}) ---\n{item[2]}" for item in results)


def _generate_sql(question: str, context: str, table_list: str, table_mapping: str, error_msg: str | None = None) -> str:
    error_section = f"\n\n## PREVIOUS ERROR:\n{error_msg}" if error_msg else ""
    system = PROMPT_SQL_GENERATION.format(
        catalog=CATALOG,
        table_list=table_list,
        table_id_mapping=table_mapping or "(Allowed Tables에서 선택)",
        error_section=error_section,
    )
    return _llm_call(system, PROMPT_SQL_USER.format(context=context, question=question), **LLM_PARAMS["sql_generation"])


def _summarize_results(question: str, sql: str, results_str: str) -> str:
    return _llm_call(
        PROMPT_SUMMARIZE_SYSTEM,
        PROMPT_SUMMARIZE_USER.format(question=question, sql=sql, results=results_str),
        **LLM_PARAMS["summarization"],
    )


def _post_check(role: str, allowed_tables: str, sql: str, results_str: str) -> str:
    return _llm_call(
        POSTCHECK_SYSTEM,
        POSTCHECK_USER.format(role=role, allowed_tables=allowed_tables, sql=sql, results=results_str),
        max_tokens=128,
        temperature=0.0,
    ).strip()


def _serialize_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no rows)"
    lines = []
    for row in rows[:20]:
        lines.append(", ".join(f"{k}={v}" for k, v in row.items()))
    return "\n".join(lines)


def _load_runtime_metadata(role_id: str, rbac_enabled: bool) -> dict[str, Any]:
    table_rows = _query_dicts(
        f"""
        SELECT table_schema, table_name, CONCAT('{CATALOG}.', table_schema, '.', table_name) AS fqn
        FROM {CATALOG}.information_schema.tables
        WHERE table_schema != 'information_schema'
        """
    )
    context_rows: list[dict[str, Any]] = []
    context_available = True
    context_error = ""
    try:
        context_rows = _query_dicts(f"SELECT table_id, layer, domain FROM {CATALOG}.search.llm_table_context")
    except Exception as error:
        # Some roles do not have USE SCHEMA on `search`; keep running with a degraded metadata mode.
        context_available = False
        context_error = str(error)

    domain_to_tables: dict[str, set[str]] = {}
    table_id_to_fqn: dict[str, str] = {}

    for ctx in context_rows:
        table_id = str(ctx.get("table_id", ""))
        last_part = table_id.split("__")[-1]
        for table in table_rows:
            table_name = str(table.get("table_name", ""))
            fqn = str(table.get("fqn", ""))
            domain = str(ctx.get("domain", ""))
            if last_part == table_name or table_name.endswith(last_part):
                domain_to_tables.setdefault(domain, set()).add(fqn)
                table_id_to_fqn[table_id] = fqn

    for domain in domain_to_tables:
        domain_to_tables[domain].add(f"{CATALOG}.silver.events")

    allowed_domains = None
    if rbac_enabled:
        role_safe = role_id.replace("'", "''")
        rows = _query_dicts(
            f"""
            SELECT DISTINCT system_name
            FROM {CATALOG}.governance.access_policies
            WHERE role_id = '{role_safe}'
            """
        )
        domains = set(UNIVERSAL_DOMAINS)
        for row in rows:
            domains.update(SYSTEM_TO_DOMAINS.get(str(row.get("system_name", "")), []))
        allowed_domains = sorted(domains)

    return {
        "table_rows": table_rows,
        "context_rows": context_rows,
        "domain_to_tables": domain_to_tables,
        "table_id_to_fqn": table_id_to_fqn,
        "allowed_domains": allowed_domains,
        "context_available": context_available,
        "context_error": context_error,
    }


def _allowed_table_list(domains: list[str], domain_to_tables: dict[str, set[str]]) -> str:
    tables: set[str] = set()
    for domain in domains:
        tables.update(domain_to_tables.get(domain, set()))
    tables.update(domain_to_tables.get("Master/Governance", set()))
    return "\n".join(f"  - {table}" for table in sorted(tables))


def _table_mapping_str(domains: list[str], context_rows: list[dict[str, Any]], table_id_to_fqn: dict[str, str]) -> str:
    lines = []
    for ctx in context_rows:
        table_id = str(ctx.get("table_id", ""))
        domain = str(ctx.get("domain", ""))
        if domain in domains and table_id in table_id_to_fqn:
            lines.append(f"  {table_id} -> {table_id_to_fqn[table_id]}")
    return "\n".join(sorted(lines))


def classify_intent(question: str) -> str:
    try:
        result = _llm_call(INTENT_SYSTEM, INTENT_USER.format(question=question), max_tokens=10, temperature=0.0)
        return "WORK" if "WORK" in result.upper() else "CHAT"
    except Exception:
        return "CHAT"


def _chat_answer(question: str) -> dict[str, Any]:
    messages = [ChatMessage(role=ChatMessageRole.SYSTEM, content=CHAT_SYSTEM_PROMPT)]
    for item in _CONVERSATION_MEMORY:
        role = ChatMessageRole.USER if item["role"] == "user" else ChatMessageRole.ASSISTANT
        messages.append(ChatMessage(role=role, content=item["content"]))
    messages.append(ChatMessage(role=ChatMessageRole.USER, content=question))

    response = _client().serving_endpoints.query(name=LLM_MODEL, messages=messages, max_tokens=1024, temperature=0.3)
    answer = response.choices[0].message.content

    _CONVERSATION_MEMORY.append({"role": "user", "content": question})
    _CONVERSATION_MEMORY.append({"role": "assistant", "content": answer})

    return {
        "request_id": str(uuid.uuid4()),
        "guard_status": "PASS",
        "answer_guard_status": "PASS",
        "blocked": False,
        "answer": answer,
        "sources": {"tables": [], "documents": []},
        "checks": {
            "rbac_enabled": False,
            "pre_check": "SKIPPED",
            "post_check": "SKIPPED",
        },
        "sql_log": {},
        "raw": {"mode": "CHAT", "status": "SUCCESS"},
    }


def _work_answer(question: str, role_id: str, rbac_enabled: bool, post_check_enabled: bool) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    meta = _load_runtime_metadata(role_id, rbac_enabled)

    domain_to_tables = meta["domain_to_tables"]
    table_id_to_fqn = meta["table_id_to_fqn"]
    context_rows = meta["context_rows"]
    table_rows = meta["table_rows"]

    context_available = bool(meta.get("context_available", True))
    pre_check_state = "PASS" if rbac_enabled else "SKIPPED"

    if rbac_enabled and context_available:
        domains = meta["allowed_domains"] or []
        table_list = _allowed_table_list(domains, domain_to_tables)
        table_mapping = _table_mapping_str(domains, context_rows, table_id_to_fqn)
    elif rbac_enabled and not context_available:
        # Fallback: allow SQL generation with catalog-wide table list when RBAC metadata cannot be loaded.
        domains = None
        table_list = "\n".join(f"  - {row.get('fqn', '')}" for row in table_rows)
        table_mapping = ""
        pre_check_state = "SKIPPED"
    else:
        domains = None
        table_list = "\n".join(f"  - {row.get('fqn', '')}" for row in table_rows)
        table_mapping = _table_mapping_str(list(domain_to_tables.keys()), context_rows, table_id_to_fqn)

    if rbac_enabled and context_available:
        unfiltered = _search_metadata(question, top_k=3)
        needed = set(str(item[3]) for item in unfiltered) - set(UNIVERSAL_DOMAINS)
        accessible = set(domains or []) - set(UNIVERSAL_DOMAINS)
        if needed and not needed.intersection(accessible):
            return {
                "request_id": request_id,
                "guard_status": "DENIED",
                "answer_guard_status": "BLOCKED",
                "blocked": True,
                "answer": MSG_ACCESS_DENIED.format(role=role_id),
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": True,
                    "pre_check": "BLOCKED",
                    "post_check": "SKIPPED",
                },
                "sql_log": {"request_id": request_id, "status": "DENIED", "blocked": True, "table_name": "-", "sql": ""},
                "raw": {"failure_reason": "RBAC_DOMAIN_DENIED"},
            }

    results = _search_metadata(question, top_k=5, allowed_domains=domains)
    if not results:
        return {
            "request_id": request_id,
            "guard_status": "DENIED",
            "answer_guard_status": "BLOCKED",
            "blocked": True,
            "answer": "검색 결과 없음",
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": rbac_enabled,
                    "pre_check": "BLOCKED" if (rbac_enabled and context_available) else pre_check_state,
                "post_check": "SKIPPED",
            },
            "sql_log": {"request_id": request_id, "status": "DENIED", "blocked": True, "table_name": "-", "sql": ""},
            "raw": {"failure_reason": "NO_SEARCH_RESULT"},
        }

    context = _build_context(results)
    searched = sorted(set(str(item[1]) for item in results))

    sql_text = _extract_sql(_generate_sql(question, context, table_list, table_mapping))
    started = time.perf_counter()

    for attempt in range(2):
        try:
            columns, rows = _execute_sql(sql_text)
            break
        except Exception as error:
            if attempt == 0:
                sql_text = _extract_sql(_generate_sql(question, context, table_list, table_mapping, error_msg=str(error)))
            else:
                return {
                    "request_id": request_id,
                    "guard_status": "ERROR",
                    "answer_guard_status": "ERROR",
                    "blocked": True,
                    "answer": str(error)[:300],
                    "sources": {"tables": [], "documents": []},
                    "checks": {
                        "rbac_enabled": rbac_enabled,
                        "pre_check": pre_check_state,
                        "post_check": "SKIPPED",
                    },
                    "sql_log": {
                        "request_id": request_id,
                        "status": "ERROR",
                        "blocked": True,
                        "table_name": ", ".join(searched),
                        "sql": sql_text,
                        "query_runtime_ms": int((time.perf_counter() - started) * 1000),
                    },
                    "raw": {"failure_reason": "SQL_EXECUTION_ERROR"},
                }

    rows = rows[:20]
    results_str = _serialize_rows(rows)

    post_status = "SKIPPED"
    if post_check_enabled and rbac_enabled:
        verdict = _post_check(role_id, table_list, sql_text, results_str)
        if verdict.upper().startswith("FAIL"):
            return {
                "request_id": request_id,
                "guard_status": "DENIED",
                "answer_guard_status": "BLOCKED",
                "blocked": True,
                "answer": f"[Post-Check] {verdict}",
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": True,
                    "pre_check": pre_check_state,
                    "post_check": "BLOCKED",
                },
                "sql_log": {
                    "request_id": request_id,
                    "status": "DENIED",
                    "blocked": True,
                    "table_name": ", ".join(searched),
                    "sql": sql_text,
                    "row_count": len(rows),
                    "column_count": len(columns),
                    "columns": columns,
                    "query_runtime_ms": int((time.perf_counter() - started) * 1000),
                },
                "raw": {"failure_reason": "POST_CHECK_FAILED"},
            }
        post_status = "PASS"

    summary = _summarize_results(question, sql_text, results_str)
    runtime_ms = int((time.perf_counter() - started) * 1000)
    tables = [str(table_id_to_fqn.get(table, table)) for table in searched]

    return {
        "request_id": request_id,
        "guard_status": "SUCCESS",
        "answer_guard_status": "PASS",
        "blocked": False,
        "answer": summary,
        "sources": {"tables": tables, "documents": []},
        "checks": {
            "rbac_enabled": rbac_enabled,
            "pre_check": pre_check_state,
            "post_check": post_status if rbac_enabled else "SKIPPED",
        },
        "sql_log": {
            "request_id": request_id,
            "query_time": _kst_now_iso(),
            "status": "SUCCESS",
            "blocked": False,
            "table_name": ", ".join(tables) if tables else "-",
            "sql": sql_text,
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": columns,
            "query_runtime_ms": runtime_ms,
        },
        "raw": {
            "request_id": request_id,
            "status": "SUCCESS",
            "execution_status": "SUCCESS",
            "role": role_id,
            "rbac_enabled": rbac_enabled,
            "post_check": post_check_enabled,
            "post_check_executed": post_check_enabled and rbac_enabled,
            "sql": sql_text,
            "columns_returned": columns,
            "row_count_returned": len(rows),
            "query_runtime_ms": runtime_ms,
        },
    }


def call_direct_rag(payload: dict[str, Any], access: dict[str, Any]) -> dict[str, Any] | None:
    if not direct_backend_configured():
        return None

    query = str(payload.get("query", "")).strip()
    role_id = str(payload.get("role_id") or "GENERAL_EMPLOYEE")
    rbac_enabled = bool(payload.get("rbac_enabled", True))
    post_check_enabled = bool(payload.get("post_check_enabled", True))

    if query.lower() == "/clear":
        _CONVERSATION_MEMORY.clear()
        return {
            "request_id": str(uuid.uuid4()),
            "guard_status": "PASS",
            "answer_guard_status": "PASS",
            "blocked": False,
            "answer": "대화 이력이 초기화되었습니다.",
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": False,
                "pre_check": "SKIPPED",
                "post_check": "SKIPPED",
            },
            "sql_log": {},
            "raw": {"mode": "SYSTEM", "status": "SUCCESS"},
        }

    try:
        if query.lower().startswith("/chat"):
            return _chat_answer(query[5:].strip())
        if query.lower().startswith("/work"):
            return _work_answer(query[5:].strip(), role_id, rbac_enabled, post_check_enabled)

        intent = classify_intent(query)
        if intent == "CHAT":
            return _chat_answer(query)
        return _work_answer(query, role_id, rbac_enabled, post_check_enabled)
    except Exception as error:
        message = str(error)[:500]
        if "INSUFFICIENT_PERMISSIONS" in message and "USE SCHEMA" in message:
            message = (
                "Databricks permission error. Grant USE SCHEMA on `cos_adb.search` and SELECT on "
                "`cos_adb.search.llm_table_context`, or switch to RAG_API_URL / DATABRICKS_JOB_ID backend."
            )
        return {
            "request_id": str(uuid.uuid4()),
            "guard_status": "ERROR",
            "answer_guard_status": "ERROR",
            "blocked": True,
            "answer": f"Direct RAG execution failed: {message}",
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": rbac_enabled,
                "pre_check": "ERROR",
                "post_check": "ERROR",
            },
            "sql_log": {},
            "raw": {"error": str(error)[:500]},
        }

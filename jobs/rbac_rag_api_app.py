import argparse
import base64
import json
import re
import time
import uuid
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from pyspark.sql.types import (
    ArrayType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampNTZType,
)


# ==============================
# 0) Static config (same as notebook)
# ==============================
llm_model = "databricks-qwen3-next-80b-a3b-instruct"
embedding_model = "databricks-qwen3-embedding-0-6b"

vs_endpoint_name = "cos-rag-endpoint"
vs_index_name = "cos_adb.search.metadata_chunks_index"
vs_source_table = "cos_adb.search.metadata_chunks"

CATALOG = "cos_adb"
LOG_TABLE = "cos_adb.governance.rag_sql_query_logs"

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

## Table Name Mapping (context 내부명 → 실제 FQN)
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

MSG_ACCESS_DENIED = "[{role}] 역할로는 해당 질문에 관련된 데이터에 접근할 수 없습니다."

LLM_PARAMS = {
    "sql_generation": {"max_tokens": 512, "temperature": 0.0},
    "summarization": {"max_tokens": 1024, "temperature": 0.1},
}

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

LOG_SCHEMA = StructType([
    StructField("log_id", StringType(), False),
    StructField("request_id", StringType(), True),
    StructField("query_time", TimestampNTZType(), True),
    StructField("user_question", StringType(), True),
    StructField("generated_sql", StringType(), True),
    StructField("tables_accessed", ArrayType(StringType()), True),
    StructField("columns_returned", ArrayType(StringType()), True),
    StructField("row_count_returned", LongType(), True),
    StructField("execution_status", StringType(), True),
    StructField("success_reason", StringType(), True),
    StructField("failure_reason", StringType(), True),
    StructField("error_message", StringType(), True),
    StructField("query_runtime_ms", LongType(), True),
    StructField("user_id", StringType(), True),
    StructField("role_id", StringType(), True),
    StructField("department_id", StringType(), True),
    StructField("permission_check", StringType(), True),
    StructField("created_at", TimestampNTZType(), True),
])


# ==============================
# 1) Runtime globals initialized in init_runtime_state()
# ==============================
w = WorkspaceClient()

SELECTED_ROLE = "GENERAL_EMPLOYEE"
RBAC_ENABLED = True
POST_CHECK_ENABLED = True
ALLOWED_DOMAINS = None

_table_rows = []
_context_rows = []
ROLE_IDS = []
DOMAIN_TO_TABLES = {}
TABLE_ID_TO_FQN = {}
RBAC_TABLE_LIST = ""


# ==============================
# 2) Shared helpers
# ==============================
def _kst_now():
    return datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)


def _normalize_on_off(value, default=True):
    if value is None:
        return default
    text = str(value).strip().upper()
    if text in {"ON", "TRUE", "1", "YES", "Y"}:
        return True
    if text in {"OFF", "FALSE", "0", "NO", "N"}:
        return False
    return default


def _get_dbutils_or_none():
    try:
        return dbutils  # type: ignore[name-defined]
    except NameError:
        return None


def _load_args_and_env():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--question", type=str, default=None)
    parser.add_argument("--question_b64", type=str, default=None)
    parser.add_argument("--question_encoding", type=str, default=None)
    parser.add_argument("--role_id", type=str, default=None)
    parser.add_argument("--user_role", type=str, default=None)
    parser.add_argument("--use_user_role_fallback", type=str, default=None)
    parser.add_argument("--rbac_enabled", type=str, default=None)
    parser.add_argument("--post_check", type=str, default=None)
    parser.add_argument("--verbose", type=str, default=None)

    args, _ = parser.parse_known_args()

    return {
        "question": args.question,
        "question_b64": args.question_b64,
        "question_encoding": args.question_encoding,
        "role_id": args.role_id,
        "user_role": args.user_role,
        "use_user_role_fallback": args.use_user_role_fallback,
        "rbac_enabled": args.rbac_enabled,
        "post_check": args.post_check,
        "verbose": args.verbose,
        "env_question": __import__("os").environ.get("QUESTION"),
        "env_question_b64": __import__("os").environ.get("QUESTION_B64"),
        "env_question_encoding": __import__("os").environ.get("QUESTION_ENCODING"),
        "env_role_id": __import__("os").environ.get("ROLE_ID"),
        "env_user_role": __import__("os").environ.get("USER_ROLE"),
        "env_use_user_role_fallback": __import__("os").environ.get("USE_USER_ROLE_FALLBACK"),
        "env_rbac_enabled": __import__("os").environ.get("RBAC_ENABLED"),
        "env_post_check": __import__("os").environ.get("POST_CHECK"),
        "env_verbose": __import__("os").environ.get("VERBOSE"),
    }


def _load_widget_params():
    params = {
        "question": None,
        "question_b64": None,
        "question_encoding": None,
        "role_id": None,
        "user_role": None,
        "use_user_role_fallback": None,
        "rbac_enabled": None,
        "post_check": None,
        "verbose": None,
    }

    d = _get_dbutils_or_none()
    if d is None:
        return params

    try:
        d.widgets.text("question", "")
        d.widgets.text("question_b64", "")
        d.widgets.text("question_encoding", "")
        d.widgets.text("role_id", "GENERAL_EMPLOYEE")
        d.widgets.text("user_role", "")
        d.widgets.dropdown("use_user_role_fallback", "OFF", ["ON", "OFF"])
        d.widgets.dropdown("rbac_enabled", "ON", ["ON", "OFF"])
        d.widgets.dropdown("post_check", "ON", ["ON", "OFF"])
        d.widgets.dropdown("verbose", "OFF", ["ON", "OFF"])
    except Exception:
        pass

    for key in params:
        try:
            params[key] = d.widgets.get(key)
        except Exception:
            pass

    return params


def load_runtime_params():
    """
    Precedence: CLI args > widgets > env > defaults
    """
    args_env = _load_args_and_env()
    widgets = _load_widget_params()

    def pick(*values, default=None):
        for value in values:
            if value is not None and str(value) != "":
                return value
        return default

    question_b64 = pick(args_env["question_b64"], widgets["question_b64"], args_env["env_question_b64"], default="")
    question_encoding = pick(args_env["question_encoding"], widgets["question_encoding"], args_env["env_question_encoding"], default="")

    if question_b64 and question_encoding == "base64_utf8":
        question = base64.b64decode(question_b64).decode("utf-8")
    else:
        question = pick(args_env["question"], widgets["question"], args_env["env_question"], default="")

    use_user_role_fallback = _normalize_on_off(
        pick(
            args_env["use_user_role_fallback"],
            widgets["use_user_role_fallback"],
            args_env["env_use_user_role_fallback"],
            default="OFF",
        ),
        False,
    )

    role_id = pick(args_env["role_id"], widgets["role_id"], args_env["env_role_id"], default="")
    if not role_id and use_user_role_fallback:
        role_id = pick(args_env["user_role"], widgets["user_role"], args_env["env_user_role"], default="")

    if not role_id:
        role_id = "GENERAL_EMPLOYEE"

    return {
        "question": question,
        "question_b64": question_b64,
        "question_encoding": question_encoding,
        "role_id": role_id,
        "user_role": pick(args_env["user_role"], widgets["user_role"], args_env["env_user_role"], default=""),
        "use_user_role_fallback": use_user_role_fallback,
        "rbac_enabled": _normalize_on_off(pick(args_env["rbac_enabled"], widgets["rbac_enabled"], args_env["env_rbac_enabled"], default="ON"), True),
        "post_check": _normalize_on_off(pick(args_env["post_check"], widgets["post_check"], args_env["env_post_check"], default="ON"), True),
        "verbose": _normalize_on_off(pick(args_env["verbose"], widgets["verbose"], args_env["env_verbose"], default="OFF"), False),
    }


def get_allowed_domains(role_id):
    rows = spark.sql(f"""
        SELECT DISTINCT system_name
        FROM cos_adb.governance.access_policies
        WHERE role_id = '{role_id}'
    """).collect()

    domains = set(UNIVERSAL_DOMAINS)
    for row in rows:
        domains.update(SYSTEM_TO_DOMAINS.get(row.system_name, []))
    return sorted(domains)


def _get_allowed_table_list(domains):
    tables = set()
    for domain in domains:
        tables.update(DOMAIN_TO_TABLES.get(domain, set()))
    tables.update(DOMAIN_TO_TABLES.get("Master/Governance", set()))
    return "\n".join(f"  - {table}" for table in sorted(tables))


def _get_table_id_mapping_str(domains):
    return "\n".join(sorted(
        f"  {ctx.table_id} -> {TABLE_ID_TO_FQN[ctx.table_id]}"
        for ctx in _context_rows if ctx.domain in domains and ctx.table_id in TABLE_ID_TO_FQN
    ))


def init_runtime_state(params):
    """
    Execution-order dependency:
    Must run once before ask_rag()/route_query() to initialize RBAC-related globals.
    """
    global SELECTED_ROLE, RBAC_ENABLED, POST_CHECK_ENABLED, ALLOWED_DOMAINS
    global _table_rows, _context_rows, ROLE_IDS, DOMAIN_TO_TABLES, TABLE_ID_TO_FQN, RBAC_TABLE_LIST

    RBAC_ENABLED = bool(params["rbac_enabled"])
    POST_CHECK_ENABLED = bool(params["post_check"])
    SELECTED_ROLE = params["role_id"]

    ROLE_IDS = [
        row.role_id
        for row in spark.sql("SELECT role_id FROM cos_adb.silver.roles ORDER BY role_id").collect()
    ]

    _table_rows = spark.sql(f"""
        SELECT table_schema, table_name, CONCAT('{CATALOG}.', table_schema, '.', table_name) AS fqn
        FROM {CATALOG}.information_schema.tables WHERE table_schema != 'information_schema'
    """).collect()

    _context_rows = spark.sql("SELECT table_id, layer, domain FROM cos_adb.search.llm_table_context").collect()

    DOMAIN_TO_TABLES = {}
    TABLE_ID_TO_FQN = {}

    for ctx in _context_rows:
        last_part = ctx.table_id.split("__")[-1]
        for table in _table_rows:
            if last_part == table.table_name or table.table_name.endswith(last_part):
                DOMAIN_TO_TABLES.setdefault(ctx.domain, set()).add(table.fqn)
                TABLE_ID_TO_FQN[ctx.table_id] = table.fqn

    for domain in DOMAIN_TO_TABLES:
        DOMAIN_TO_TABLES[domain].add(f"{CATALOG}.silver.events")

    ALLOWED_DOMAINS = get_allowed_domains(SELECTED_ROLE) if RBAC_ENABLED else None

    if ALLOWED_DOMAINS:
        RBAC_TABLE_LIST = _get_allowed_table_list(ALLOWED_DOMAINS)
    else:
        RBAC_TABLE_LIST = "\n".join(f"  - {row.fqn}" for row in _table_rows)


def _llm_call(system, user, max_tokens=512, temperature=0.0):
    response = w.serving_endpoints.query(
        name=llm_model,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
            ChatMessage(role=ChatMessageRole.USER, content=user),
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


def extract_sql(text):
    matched = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL)
    return matched.group(1).strip() if matched else text.strip()


def search_metadata(query, top_k=5, allowed_domains=None):
    kwargs = {
        "index_name": vs_index_name,
        "query_text": query,
        "num_results": top_k,
        "columns": ["source_type", "source_id", "chunk_text", "domain"],
    }
    if allowed_domains:
        kwargs["filters_json"] = json.dumps({"domain": allowed_domains})
    return w.vector_search_indexes.query_index(**kwargs).result.data_array


def build_context(results):
    return "\n\n".join(f"--- [{item[0]}] {item[1]} ({item[3]}) ---\n{item[2]}" for item in results)


def generate_sql(question, context, table_list, table_id_mapping="", error_msg=None):
    error_section = f"\n\n## PREVIOUS ERROR:\n{error_msg}" if error_msg else ""
    system = PROMPT_SQL_GENERATION.format(
        catalog=CATALOG,
        table_list=table_list,
        table_id_mapping=table_id_mapping or "(Allowed Tables에서 선택)",
        error_section=error_section,
    )
    return _llm_call(
        system,
        PROMPT_SQL_USER.format(context=context, question=question),
        **LLM_PARAMS["sql_generation"],
    )


def summarize_results(question, sql, results_str):
    return _llm_call(
        PROMPT_SUMMARIZE_SYSTEM,
        PROMPT_SUMMARIZE_USER.format(question=question, sql=sql, results=results_str),
        **LLM_PARAMS["summarization"],
    )


def _extract_tables(output):
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

    return sorted({
        item.get("table")
        for item in (output.get("table_access") or [])
        if isinstance(item, dict) and item.get("table")
    })


def save_rag_log(output):
    try:
        execution_status = output.get("execution_status")

        record = {
            "log_id": str(uuid.uuid4()),
            "request_id": output.get("request_id"),
            "query_time": output.get("query_time"),
            "user_question": output.get("question"),
            "generated_sql": output.get("sql"),
            "tables_accessed": _extract_tables(output),
            "columns_returned": output.get("columns_returned") or [],
            "row_count_returned": output.get("row_count_returned"),
            "execution_status": execution_status,
            "success_reason": output.get("success_reason"),
            "failure_reason": output.get("failure_reason"),
            "error_message": output.get("detail") if execution_status == "FAILED" else None,
            "query_runtime_ms": output.get("query_runtime_ms"),
            "user_id": output.get("user_id"),
            "role_id": output.get("role"),
            "department_id": output.get("department_id"),
            "permission_check": output.get("permission_check"),
            "created_at": _kst_now(),
        }

        (
            spark.createDataFrame([record], schema=LOG_SCHEMA)
            .write
            .format("delta")
            .mode("append")
            .saveAsTable(LOG_TABLE)
        )

        print(f"[LOG SAVED] log_id={record['log_id']}, status={execution_status}")
        return record["log_id"]

    except Exception as error:
        print(f"[LOG ERROR] {str(error)[:500]}")
        return None


def _post_check(role, allowed_tables, sql, results_str):
    return _llm_call(
        POSTCHECK_SYSTEM,
        POSTCHECK_USER.format(role=role, allowed_tables=allowed_tables, sql=sql, results=results_str),
        max_tokens=128,
        temperature=0.0,
    ).strip()


def _format_output(output):
    lines = [
        f"[{output['status']}] role={output['role']} rbac={'ON' if output['rbac_enabled'] else 'OFF'} post_check={'ON' if output['post_check'] else 'OFF'}"
    ]
    lines += [f"  {entry['table']} -> {entry['result']}" for entry in output["table_access"]]
    if output["detail"]:
        lines.append(f"  message: {output['detail']}")
    if output["sql"]:
        lines.append(f"  sql: {output['sql']}")
    if output["summary"]:
        lines.append(f"  summary: {output['summary']}")
    return "\n".join(lines)


def ask_rag(question, top_k=5, role_id=None, verbose=True):
    use_rbac, use_post_check = RBAC_ENABLED, POST_CHECK_ENABLED
    active_role = (role_id or SELECTED_ROLE) if use_rbac else None

    request_id = str(uuid.uuid4())
    request_time = _kst_now()

    if use_rbac:
        domains = get_allowed_domains(active_role) if role_id else ALLOWED_DOMAINS
        table_list = _get_allowed_table_list(domains) if role_id else RBAC_TABLE_LIST
        tid_mapping = _get_table_id_mapping_str(domains)
    else:
        domains = None
        table_list = "\n".join(f"  - {row.fqn}" for row in _table_rows)
        tid_mapping = _get_table_id_mapping_str([d for d in DOMAIN_TO_TABLES])

    output = {
        "request_id": request_id,
        "query_time": request_time,
        "question": question,
        "role": active_role,
        "rbac_enabled": use_rbac,
        "post_check": use_post_check,
        "post_check_executed": False,
        "status": None,
        "execution_status": None,
        "permission_check": None,
        "success_reason": None,
        "failure_reason": None,
        "query_runtime_ms": None,
        "table_access": [],
        "sql": None,
        "columns_returned": [],
        "row_count_returned": None,
        "data": None,
        "summary": None,
        "detail": None,
    }

    if use_rbac:
        unfiltered = search_metadata(question, top_k=3)
        needed = set(item[3] for item in unfiltered) - set(UNIVERSAL_DOMAINS)
        accessible = set(domains) - set(UNIVERSAL_DOMAINS)
        if needed and not needed.intersection(accessible):
            output["table_access"] = [
                {"table": TABLE_ID_TO_FQN.get(item[1], item[1]), "result": "DENIED"}
                for item in unfiltered
                if item[3] not in set(UNIVERSAL_DOMAINS)
            ]
            output["status"] = "DENIED"
            output["detail"] = MSG_ACCESS_DENIED.format(role=active_role)
            output["execution_status"] = "BLOCKED"
            output["permission_check"] = "DENY"
            output["failure_reason"] = "RBAC_DOMAIN_DENIED"

            save_rag_log(output)
            if verbose:
                print(_format_output(output))
            return output

    results = search_metadata(question, top_k, allowed_domains=domains)
    if not results:
        output["status"] = "DENIED"
        output["detail"] = "검색 결과 없음"
        output["execution_status"] = "BLOCKED"
        output["permission_check"] = "DENY"
        output["failure_reason"] = "NO_SEARCH_RESULT"

        save_rag_log(output)
        if verbose:
            print(_format_output(output))
        return output

    context = build_context(results)
    searched = sorted(set(item[1] for item in results))

    sql = extract_sql(generate_sql(question, context, table_list, tid_mapping))
    output["sql"] = sql

    query_started = time.perf_counter()
    for attempt in range(2):
        try:
            df = spark.sql(sql)
            pdf = df.limit(20).toPandas()
            output["data"] = df
            output["columns_returned"] = list(pdf.columns)
            output["row_count_returned"] = len(pdf)
            output["query_runtime_ms"] = int((time.perf_counter() - query_started) * 1000)
            output["execution_status"] = "SUCCESS"
            break
        except Exception as error:
            if attempt == 0:
                sql = extract_sql(generate_sql(question, context, table_list, tid_mapping, error_msg=str(error)))
                output["sql"] = sql
            else:
                output["table_access"] = [
                    {"table": TABLE_ID_TO_FQN.get(table, table), "result": "ERROR"}
                    for table in searched
                ]
                output["status"] = "ERROR"
                output["detail"] = str(error)[:300]
                output["execution_status"] = "FAILED"
                output["permission_check"] = "ALLOW" if use_rbac else None
                output["failure_reason"] = "SQL_EXECUTION_ERROR"
                output["query_runtime_ms"] = int((time.perf_counter() - query_started) * 1000)
                output["row_count_returned"] = 0

                save_rag_log(output)
                if verbose:
                    print(_format_output(output))
                return output

    results_str = pdf.to_string(index=False)
    if use_post_check and use_rbac:
        output["post_check_executed"] = True
        verdict = _post_check(active_role, table_list, sql, results_str)
        if verdict.upper().startswith("FAIL"):
            output["table_access"] = [
                {"table": TABLE_ID_TO_FQN.get(table, table), "result": "DENIED"}
                for table in searched
            ]
            output["status"] = "DENIED"
            output["detail"] = f"[Post-Check] {verdict}"
            output["data"] = None
            output["execution_status"] = "SUCCESS"
            output["permission_check"] = "DENY"
            output["success_reason"] = "SQL_EXECUTED"
            output["failure_reason"] = "POST_CHECK_FAILED"

            save_rag_log(output)
            if verbose:
                print(_format_output(output))
            return output

    try:
        output["summary"] = summarize_results(question, sql, results_str)
    except Exception as error:
        output["status"] = "ERROR"
        output["execution_status"] = "SUCCESS"
        output["permission_check"] = "ALLOW" if use_rbac else None
        output["success_reason"] = "SQL_EXECUTED"
        output["failure_reason"] = "SUMMARY_GENERATION_ERROR"
        output["detail"] = str(error)[:300]

        save_rag_log(output)
        if verbose:
            print(_format_output(output))
        return output

    output["table_access"] = [
        {"table": TABLE_ID_TO_FQN.get(table, table), "result": "SUCCESS"}
        for table in searched
    ]
    output["status"] = "SUCCESS"
    output["execution_status"] = "SUCCESS"
    output["permission_check"] = "ALLOW" if use_rbac else None
    output["success_reason"] = "SQL_EXECUTED_AND_RESPONSE_RETURNED"
    output["failure_reason"] = None

    save_rag_log(output)

    if verbose:
        print(_format_output(output))
        display(df.limit(20))

    return output


class ConversationMemory:
    def __init__(self, max_turns=10):
        self._history = deque(maxlen=max_turns * 2)

    def add(self, role, content):
        self._history.append({"role": role, "content": content})

    def get_messages(self):
        return list(self._history)

    def clear(self):
        self._history.clear()
        print("[MEMORY] 대화 이력 초기화됨")

    def __len__(self):
        return len(self._history) // 2


conversation_memory = ConversationMemory(max_turns=10)


def handle_chat(question, memory):
    messages = [ChatMessage(role=ChatMessageRole.SYSTEM, content=CHAT_SYSTEM_PROMPT)]

    for msg in memory.get_messages():
        role = ChatMessageRole.USER if msg["role"] == "user" else ChatMessageRole.ASSISTANT
        messages.append(ChatMessage(role=role, content=msg["content"]))

    messages.append(ChatMessage(role=ChatMessageRole.USER, content=question))

    response = w.serving_endpoints.query(
        name=llm_model,
        messages=messages,
        max_tokens=1024,
        temperature=0.3,
    )
    answer = response.choices[0].message.content

    memory.add("user", question)
    memory.add("assistant", answer)

    return {
        "request_id": str(uuid.uuid4()),
        "query_time": _kst_now(),
        "mode": "CHAT",
        "status": "SUCCESS",
        "execution_status": "SUCCESS",
        "question": question,
        "answer": answer,
        "summary": answer,
        "detail": None,
        "conversation_turns": len(memory),
    }


def classify_intent(question):
    try:
        result = _llm_call(
            INTENT_SYSTEM,
            INTENT_USER.format(question=question),
            max_tokens=10,
            temperature=0.0,
        ).strip().upper()
        return "WORK" if "WORK" in result else "CHAT"
    except Exception:
        # Fail closed to CHAT to avoid accidental data-path execution on classifier failure.
        return "CHAT"


def route_query(question, role_id=None, verbose=True):
    raw = question.strip()

    if raw.lower().startswith("/chat"):
        mode = "CHAT"
        clean = raw[5:].strip()
    elif raw.lower().startswith("/work"):
        mode = "WORK"
        clean = raw[5:].strip()
    elif raw.lower() == "/clear":
        conversation_memory.clear()
        return {
            "mode": "SYSTEM",
            "status": "SUCCESS",
            "answer": "대화 이력이 초기화되었습니다.",
            "summary": "대화 이력이 초기화되었습니다.",
        }
    else:
        mode = classify_intent(raw)
        clean = raw

    if not clean:
        return {"mode": mode, "status": "ERROR", "detail": "질문 내용이 비어있습니다."}

    if verbose:
        print(f"[ROUTER] mode={mode} | question={clean[:60]}")

    if mode == "CHAT":
        return handle_chat(clean, conversation_memory)

    result = ask_rag(clean, role_id=role_id, verbose=verbose)
    result["mode"] = "WORK"
    return result


def build_api_response(result):
    mode = result.get("mode", "WORK")
    status = result.get("status", "UNKNOWN")
    blocked = status in ["DENIED", "BLOCKED"]

    if mode == "CHAT":
        return {
            "request_id": result.get("request_id"),
            "mode": "CHAT",
            "answer": result.get("answer", ""),
            "guard_status": "PASS",
            "answer_guard_status": "PASS",
            "blocked": False,
            "conversation_turns": result.get("conversation_turns", 0),
            "sources": {"tables": [], "documents": []},
            "checks": {
                "rbac_enabled": False,
                "pre_check": "SKIPPED",
                "post_check": "SKIPPED",
            },
        }

    if mode == "SYSTEM":
        return {
            "mode": "SYSTEM",
            "answer": result.get("answer", ""),
            "guard_status": "PASS",
            "answer_guard_status": "PASS",
            "blocked": False,
        }

    table_access = result.get("table_access", [])
    allowed_tables = [
        str(item.get("table"))
        for item in table_access
        if isinstance(item, dict) and item.get("result") not in ["DENIED", "BLOCKED"]
    ]

    if not bool(result.get("rbac_enabled", True)):
        post_check_status = "SKIPPED"
    elif not bool(result.get("post_check", True)):
        post_check_status = "SKIPPED"
    elif not bool(result.get("post_check_executed", False)):
        post_check_status = "SKIPPED"
    elif result.get("failure_reason") == "POST_CHECK_FAILED":
        post_check_status = "BLOCKED"
    else:
        post_check_status = "PASS"

    return {
        "request_id": result.get("request_id"),
        "mode": "WORK",
        "answer": result.get("summary") or result.get("detail") or "",
        "guard_status": status,
        "answer_guard_status": "PASS" if not blocked else "BLOCKED",
        "blocked": blocked,
        "sources": {
            "tables": [] if blocked else allowed_tables,
            "documents": [],
        },
        "checks": {
            "rbac_enabled": bool(result.get("rbac_enabled", True)),
            "pre_check": "BLOCKED" if status == "DENIED" else "PASS",
            "post_check": post_check_status,
        },
        "raw": result,
    }


def emit_json_response(response):
    payload = json.dumps(response, ensure_ascii=False, default=str)
    print(payload)

    d = _get_dbutils_or_none()
    if d is not None:
        try:
            d.notebook.exit(payload)
        except Exception:
            pass


# ==============================
# 3) Main entrypoint
# ==============================
def main():
    try:
        params = load_runtime_params()

        init_runtime_state(params)

        if params["verbose"]:
            print(f"FINAL question = {params['question']}")
            print(f"FINAL role_id  = {params['role_id']}")
            print(f"RBAC_ENABLED   = {params['rbac_enabled']}")
            print(f"POST_CHECK     = {params['post_check']}")

        result = route_query(
            params["question"],
            role_id=params["role_id"],
            verbose=params["verbose"],
        )

        response = build_api_response(result)
        emit_json_response(response)
    except Exception as error:
        emit_json_response({
            "mode": "SYSTEM",
            "guard_status": "ERROR",
            "answer_guard_status": "ERROR",
            "blocked": True,
            "answer": f"Unhandled runtime error: {str(error)[:500]}",
            "checks": {
                "rbac_enabled": False,
                "pre_check": "ERROR",
                "post_check": "ERROR",
            },
        })


if __name__ == "__main__":
    main()

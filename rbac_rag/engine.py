import time
import uuid
from typing import Any

from .llm import DatabricksLLM
from .logging_utils import kst_now, save_rag_log
from .mappings import TableMappings
from .prompts import MSG_ACCESS_DENIED
from .rbac import UNIVERSAL_DOMAINS, get_allowed_domains
from .settings import RagSettings


class RagEngine:
    def __init__(
        self,
        *,
        spark: Any,
        llm: DatabricksLLM,
        settings: RagSettings,
        mappings: TableMappings,
        selected_role: str,
        rbac_enabled: bool,
        post_check_enabled: bool,
        allowed_domains: list[str] | None,
    ):
        self.spark = spark
        self.llm = llm
        self.settings = settings
        self.mappings = mappings
        self.selected_role = selected_role
        self.rbac_enabled = rbac_enabled
        self.post_check_enabled = post_check_enabled
        self.allowed_domains = allowed_domains or []

        self.rbac_table_list = (
            self.mappings.get_allowed_table_list(self.allowed_domains)
            if self.allowed_domains
            else self.mappings.get_all_table_list()
        )

    def ask_rag(
        self,
        question: str,
        *,
        top_k: int | None = None,
        role_id: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        top_k = top_k or self.settings.top_k_default
        use_rbac = self.rbac_enabled
        use_post_check = self.post_check_enabled
        active_role = (role_id or self.selected_role) if use_rbac else None

        request_id = str(uuid.uuid4())
        request_time = kst_now()

        if use_rbac:
            domains = get_allowed_domains(self.spark, active_role) if role_id else self.allowed_domains
            table_list = self.mappings.get_allowed_table_list(domains) if role_id else self.rbac_table_list
            table_id_mapping = self.mappings.get_table_id_mapping_str(domains)
        else:
            domains = None
            table_list = self.mappings.get_all_table_list()
            table_id_mapping = self.mappings.get_table_id_mapping_str(self.mappings.get_all_domains())

        output: dict[str, Any] = {
            "request_id": request_id,
            "query_time": request_time,
            "question": question,
            "role": active_role,
            "rbac_enabled": use_rbac,
            "post_check": use_post_check,
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
            unfiltered = self.llm.search_metadata(
                question,
                top_k=3,
                vs_index_name=self.settings.vs_index_name,
            )
            needed = set(row[3] for row in unfiltered) - set(UNIVERSAL_DOMAINS)
            accessible = set(domains) - set(UNIVERSAL_DOMAINS)
            if needed and not needed.intersection(accessible):
                output["table_access"] = [
                    {
                        "table": self.mappings.table_id_to_fqn.get(row[1], row[1]),
                        "result": "DENIED",
                    }
                    for row in unfiltered
                    if row[3] not in set(UNIVERSAL_DOMAINS)
                ]
                output["status"] = "DENIED"
                output["detail"] = MSG_ACCESS_DENIED.format(role=active_role)
                output["execution_status"] = "BLOCKED"
                output["permission_check"] = "DENY"
                output["failure_reason"] = "RBAC_DOMAIN_DENIED"
                save_rag_log(self.spark, self.settings.log_table, output)
                if verbose:
                    print(format_output(output))
                return output

        results = self.llm.search_metadata(
            question,
            top_k=top_k,
            vs_index_name=self.settings.vs_index_name,
            allowed_domains=domains,
        )
        if not results:
            output["status"] = "DENIED"
            output["detail"] = "검색 결과 없음"
            output["execution_status"] = "BLOCKED"
            output["permission_check"] = "DENY"
            output["failure_reason"] = "NO_SEARCH_RESULT"
            save_rag_log(self.spark, self.settings.log_table, output)
            if verbose:
                print(format_output(output))
            return output

        context = self.llm.build_context(results)
        searched = sorted(set(row[1] for row in results))

        sql = self.llm.extract_sql(
            self.llm.generate_sql(
                question,
                context,
                table_list,
                table_id_mapping=table_id_mapping,
            )
        )
        output["sql"] = sql

        query_started = time.perf_counter()
        for attempt in range(2):
            try:
                df = self.spark.sql(sql)
                pdf = df.limit(20).toPandas()
                output["data"] = df
                output["columns_returned"] = list(pdf.columns)
                output["row_count_returned"] = len(pdf)
                output["query_runtime_ms"] = int((time.perf_counter() - query_started) * 1000)
                output["execution_status"] = "SUCCESS"
                break
            except Exception as error:
                if attempt == 0:
                    sql = self.llm.extract_sql(
                        self.llm.generate_sql(
                            question,
                            context,
                            table_list,
                            table_id_mapping=table_id_mapping,
                            error_msg=str(error),
                        )
                    )
                    output["sql"] = sql
                else:
                    output["table_access"] = [
                        {
                            "table": self.mappings.table_id_to_fqn.get(table, table),
                            "result": "ERROR",
                        }
                        for table in searched
                    ]
                    output["status"] = "ERROR"
                    output["detail"] = str(error)[:300]
                    output["execution_status"] = "FAILED"
                    output["permission_check"] = "ALLOW" if use_rbac else None
                    output["failure_reason"] = "SQL_EXECUTION_ERROR"
                    output["query_runtime_ms"] = int((time.perf_counter() - query_started) * 1000)
                    output["row_count_returned"] = 0
                    save_rag_log(self.spark, self.settings.log_table, output)
                    if verbose:
                        print(format_output(output))
                    return output

        results_str = pdf.to_string(index=False)
        if use_post_check and use_rbac:
            verdict = self.llm.post_check(active_role, table_list, sql, results_str)
            if verdict.upper().startswith("FAIL"):
                output["table_access"] = [
                    {
                        "table": self.mappings.table_id_to_fqn.get(table, table),
                        "result": "DENIED",
                    }
                    for table in searched
                ]
                output["status"] = "DENIED"
                output["detail"] = f"[Post-Check] {verdict}"
                output["data"] = None
                output["execution_status"] = "SUCCESS"
                output["permission_check"] = "DENY"
                output["success_reason"] = "SQL_EXECUTED"
                output["failure_reason"] = "POST_CHECK_FAILED"
                save_rag_log(self.spark, self.settings.log_table, output)
                if verbose:
                    print(format_output(output))
                return output

        try:
            output["summary"] = self.llm.summarize_results(question, sql, results_str)
        except Exception as error:
            output["status"] = "ERROR"
            output["execution_status"] = "SUCCESS"
            output["permission_check"] = "ALLOW" if use_rbac else None
            output["success_reason"] = "SQL_EXECUTED"
            output["failure_reason"] = "SUMMARY_GENERATION_ERROR"
            output["detail"] = str(error)[:300]
            save_rag_log(self.spark, self.settings.log_table, output)
            if verbose:
                print(format_output(output))
            return output

        output["table_access"] = [
            {"table": self.mappings.table_id_to_fqn.get(table, table), "result": "SUCCESS"}
            for table in searched
        ]
        output["status"] = "SUCCESS"
        output["execution_status"] = "SUCCESS"
        output["permission_check"] = "ALLOW" if use_rbac else None
        output["success_reason"] = "SQL_EXECUTED_AND_RESPONSE_RETURNED"
        output["failure_reason"] = None

        save_rag_log(self.spark, self.settings.log_table, output)

        if verbose:
            print(format_output(output))
            display(df.limit(20))

        return output


def format_output(output: dict[str, Any]) -> str:
    lines = [
        f"[{output['status']}] role={output['role']} "
        f"rbac={'ON' if output['rbac_enabled'] else 'OFF'} "
        f"post_check={'ON' if output['post_check'] else 'OFF'}"
    ]
    lines += [f"  {entry['table']} -> {entry['result']}" for entry in output["table_access"]]
    if output["detail"]:
        lines.append(f"  message: {output['detail']}")
    if output["sql"]:
        lines.append(f"  sql: {output['sql']}")
    if output["summary"]:
        lines.append(f"  summary: {output['summary']}")
    return "\n".join(lines)


def get_result(output: dict[str, Any], mode: str = "admin") -> dict[str, Any]:
    if mode == "admin":
        return {key: value for key, value in output.items() if key != "data"}
    if output["status"] == "SUCCESS":
        return {
            "answer": output["summary"],
            "data": output["data"].limit(20).toPandas().to_dict(orient="records") if output["data"] else [],
        }
    return {"answer": output["detail"] or "요청을 처리할 수 없습니다."}
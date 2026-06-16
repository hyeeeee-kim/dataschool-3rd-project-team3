from dataclasses import dataclass, field


@dataclass(frozen=True)
class RagSettings:
    llm_model: str = "databricks-qwen3-next-80b-a3b-instruct"
    embedding_model: str = "databricks-qwen3-embedding-0-6b"
    vs_endpoint_name: str = "cos-rag-endpoint"
    vs_index_name: str = "cos_adb.search.metadata_chunks_index"
    vs_source_table: str = "cos_adb.search.metadata_chunks"
    catalog: str = "cos_adb"
    log_table: str = "cos_adb.governance.rag_sql_query_logs"
    top_k_default: int = 5


@dataclass
class RuntimeFlags:
    selected_role: str = "GENERAL_EMPLOYEE"
    rbac_enabled: bool = True
    post_check_enabled: bool = True
    question: str = ""
    allowed_domains: list[str] = field(default_factory=list)
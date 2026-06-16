import base64
from dataclasses import dataclass
from typing import Any


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


@dataclass
class WidgetInput:
    question: str
    role_id: str
    rbac_enabled: bool
    post_check_enabled: bool


def get_allowed_domains(spark: Any, role_id: str) -> list[str]:
    rows = spark.sql(
        f"""
        SELECT DISTINCT system_name
        FROM cos_adb.governance.access_policies
        WHERE role_id = '{role_id}'
        """
    ).collect()

    domains = set(UNIVERSAL_DOMAINS)
    for row in rows:
        domains.update(SYSTEM_TO_DOMAINS.get(row.system_name, []))
    return sorted(domains)


def list_role_ids(spark: Any) -> list[str]:
    return [
        row.role_id
        for row in spark.sql("SELECT role_id FROM cos_adb.silver.roles ORDER BY role_id").collect()
    ]


def parse_widget_input(dbutils: Any) -> WidgetInput:
    question_b64 = dbutils.widgets.get("question_b64")
    question_encoding = dbutils.widgets.get("question_encoding")

    if question_b64 and question_encoding == "base64_utf8":
        question = base64.b64decode(question_b64).decode("utf-8")
    else:
        question = dbutils.widgets.get("question")

    return WidgetInput(
        question=question,
        role_id=dbutils.widgets.get("role_id"),
        rbac_enabled=dbutils.widgets.get("rbac_enabled") == "ON",
        post_check_enabled=dbutils.widgets.get("post_check") == "ON",
    )


def ensure_widgets(dbutils: Any, role_ids: list[str]) -> None:
    dbutils.widgets.text("question", "")
    dbutils.widgets.text("question_b64", "")
    dbutils.widgets.text("question_encoding", "")
    dbutils.widgets.text("role_id", "GENERAL_EMPLOYEE")

    try:
        job_role = dbutils.widgets.get("role_id")
    except Exception:
        job_role = "GENERAL_EMPLOYEE"

    try:
        dbutils.widgets.dropdown("rbac_enabled", "ON", ["ON", "OFF"], "RBAC")
    except Exception:
        pass

    try:
        dbutils.widgets.dropdown("post_check", "ON", ["ON", "OFF"], "Post-Check")
    except Exception:
        pass

    try:
        dbutils.widgets.dropdown("user_role", job_role, role_ids, "Role")
    except Exception:
        pass


def resolve_selected_role(dbutils: Any) -> str:
    try:
        return dbutils.widgets.get("role_id")
    except Exception:
        return dbutils.widgets.get("user_role")
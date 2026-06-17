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


def get_allowed_domains(role_id: str) -> list[str]:
    from .db_client import run_query

    rows = run_query(
        f"""
        SELECT DISTINCT system_name
        FROM cos_adb.governance.access_policies
        WHERE role_id = '{role_id}'
        """
    )
    domains = set(UNIVERSAL_DOMAINS)
    for row in rows:
        domains.update(SYSTEM_TO_DOMAINS.get(row.system_name, []))
    return sorted(domains)
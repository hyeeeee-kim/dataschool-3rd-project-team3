"""
Databricks SQL connector helper – replaces Spark for FastAPI deployment.
All SQL queries go through this module instead of spark.sql().
"""
from __future__ import annotations

import os
import types
from typing import Any

import pandas as pd


def _conn_params() -> dict[str, str]:
    host = os.getenv("DATABRICKS_HOST", "").strip()
    if not host:
        server_hostname = os.getenv("DATABRICKS_SERVER_HOSTNAME", "").strip()
        if server_hostname:
            host = server_hostname if server_hostname.startswith("http") else f"https://{server_hostname}"
    host = host.rstrip("/").replace("https://", "")
    http_path = os.getenv("DATABRICKS_HTTP_PATH", "").strip()
    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()
    if not http_path and warehouse_id:
        http_path = f"/sql/1.0/warehouses/{warehouse_id}"
    token = os.getenv("DATABRICKS_TOKEN", "").strip()
    client_id = os.getenv("DATABRICKS_CLIENT_ID", "").strip()
    client_secret = os.getenv("DATABRICKS_CLIENT_SECRET", "").strip()

    if not host or not http_path:
        raise RuntimeError(
            "DATABRICKS_HOST (or DATABRICKS_SERVER_HOSTNAME) and either DATABRICKS_HTTP_PATH or DATABRICKS_WAREHOUSE_ID must be set"
        )

    params: dict[str, str] = {"server_hostname": host, "http_path": http_path}
    if token:
        params["access_token"] = token
    elif client_id and client_secret:
        params["client_id"] = client_id
        params["client_secret"] = client_secret
    else:
        raise RuntimeError(
            "Either DATABRICKS_TOKEN or "
            "DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET must be set in .env"
        )
    return params


def run_query(sql: str) -> list[Any]:
    """Execute SQL and return list of SimpleNamespace objects (attribute access)."""
    from databricks import sql as dbsql

    with dbsql.connect(**_conn_params()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            cols = [d[0] for d in cursor.description]
            return [
                types.SimpleNamespace(**dict(zip(cols, row)))
                for row in cursor.fetchall()
            ]


def run_query_df(sql: str) -> pd.DataFrame:
    """Execute SQL and return a pandas DataFrame (max 20 rows enforced by caller)."""
    from databricks import sql as dbsql

    with dbsql.connect(**_conn_params()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            cols = [d[0] for d in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=cols)


def run_statement(sql: str) -> None:
    """Execute a DML statement (INSERT, MERGE, etc.)."""
    from databricks import sql as dbsql

    with dbsql.connect(**_conn_params()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)

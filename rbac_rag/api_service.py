"""
FastAPI adapter – replaces the Databricks Job / notebook path.
RagApiService wraps RagEngine + QueryRouter without requiring spark or dbutils.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable

from .engine import RagEngine
from .llm import ConversationMemory, DatabricksLLM
from .mappings import TableMappings
from .router import QueryRouter
from .settings import RagSettings


class RagApiService:
    """Singleton-friendly service initialised once at FastAPI startup."""

    def __init__(self) -> None:
        settings = RagSettings()
        llm = DatabricksLLM(settings)
        mappings = TableMappings.build(settings.catalog)
        engine = RagEngine(
            llm=llm,
            settings=settings,
            mappings=mappings,
            selected_role="GENERAL_EMPLOYEE",
            rbac_enabled=True,
            post_check_enabled=True,
            allowed_domains=[],
        )
        self.router = QueryRouter(rag_engine=engine, llm=llm)
        self.llm = llm
        self.engine = engine
        self.settings = settings
        # Keep this lower than Databricks Apps gateway timeout to avoid raw 504s.
        self.work_timeout_seconds = int(os.getenv("RAG_WORK_TIMEOUT_SECONDS", "45"))
        # NOTE: shared per-process memory; fine for single-user demo.
        self._memory = ConversationMemory(max_turns=10)

    # ------------------------------------------------------------------
    # Public interface expected by app/main.py
    # ------------------------------------------------------------------

    def chat(
        self,
        question: str,
        role_id: str,
        mode: str = "auto",
        rbac_enabled: bool = True,
        post_check: bool = True,
        top_k: int | None = None,
        event_callback: Callable | None = None,
    ) -> dict[str, Any]:
        raw = question.strip()

        # ── resolve mode ──────────────────────────────────────────────
        if mode == "chat" or raw.lower().startswith("/chat"):
            resolved_mode = "CHAT"
            clean = raw[5:].strip() if raw.lower().startswith("/chat") else raw
        elif mode == "work" or raw.lower().startswith("/work"):
            resolved_mode = "WORK"
            clean = raw[5:].strip() if raw.lower().startswith("/work") else raw
        elif raw.lower() == "/clear":
            self._memory.clear()
            return {
                "mode": "SYSTEM",
                "answer": "대화 이력이 초기화되었습니다.",
                "guard_status": "PASS",
                "answer_guard_status": "PASS",
                "blocked": False,
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": False,
                    "pre_check": "SKIPPED",
                    "post_check": "SKIPPED",
                },
            }
        else:
            resolved_mode = self.llm.classify_intent(raw)
            clean = raw

        if not clean:
            return {
                "mode": resolved_mode,
                "answer": "질문 내용이 비어있습니다.",
                "guard_status": "ERROR",
                "answer_guard_status": "ERROR",
                "blocked": True,
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": rbac_enabled,
                    "pre_check": "ERROR",
                    "post_check": "ERROR",
                },
            }

        # ── CHAT mode ─────────────────────────────────────────────────
        if resolved_mode == "CHAT":
            result = self.llm.handle_chat(clean, self._memory)
            return {
                "request_id": result.get("request_id"),
                "mode": "CHAT",
                "answer": result.get("answer", ""),
                "guard_status": "PASS",
                "answer_guard_status": "PASS",
                "blocked": False,
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": False,
                    "pre_check": "SKIPPED",
                    "post_check": "SKIPPED",
                },
                "raw": result,
            }

        # ── WORK mode (RAG + SQL) ─────────────────────────────────────
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.engine.ask_rag,
                    clean,
                    role_id=role_id,
                    top_k=top_k,
                    verbose=False,
                    rbac_enabled=rbac_enabled,
                    post_check_enabled=post_check,
                )
                result = future.result(timeout=self.work_timeout_seconds)
        except FuturesTimeoutError:
            return {
                "request_id": "REQ-RAG-TIMEOUT",
                "mode": "WORK",
                "answer": f"요청이 {self.work_timeout_seconds}초를 초과해 중단되었습니다. SQL Warehouse 상태/권한과 Vector Search 권한을 확인해 주세요.",
                "guard_status": "ERROR",
                "answer_guard_status": "ERROR",
                "blocked": True,
                "sources": {"tables": [], "documents": []},
                "checks": {
                    "rbac_enabled": rbac_enabled,
                    "pre_check": "ERROR",
                    "post_check": "ERROR",
                },
                "sql_log": {},
                "raw": {},
            }
        result["mode"] = "WORK"
        status = result.get("status", "UNKNOWN")
        blocked = status in {"DENIED", "BLOCKED", "ERROR"}

        table_access = result.get("table_access") or []
        allowed_tables = [
            str(item.get("table"))
            for item in table_access
            if isinstance(item, dict)
            and item.get("result") not in {"DENIED", "BLOCKED", "ERROR"}
        ]

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
                "rbac_enabled": bool(result.get("rbac_enabled", rbac_enabled)),
                "pre_check": "BLOCKED" if status == "DENIED" else "PASS",
                "post_check": "PASS" if post_check else "SKIPPED",
            },
            "sql_log": {
                "request_id": result.get("request_id"),
                "query_time": str(result.get("query_time", "")),
                "generated_sql": result.get("sql"),
                "row_count_returned": result.get("row_count_returned"),
                "columns": result.get("columns_returned") or [],
            },
            "raw": result,
        }

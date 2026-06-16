from typing import Any

from .engine import RagEngine
from .llm import ConversationMemory, DatabricksLLM


class QueryRouter:
    def __init__(self, rag_engine: RagEngine, llm: DatabricksLLM, memory_turns: int = 10):
        self.rag_engine = rag_engine
        self.llm = llm
        self.memory = ConversationMemory(max_turns=memory_turns)

    def route_query(self, question: str, role_id: str | None = None, verbose: bool = True) -> dict[str, Any]:
        raw = question.strip()

        if raw.lower().startswith("/chat"):
            mode = "CHAT"
            clean = raw[5:].strip()
        elif raw.lower().startswith("/work"):
            mode = "WORK"
            clean = raw[5:].strip()
        elif raw.lower() == "/clear":
            self.memory.clear()
            return {
                "mode": "SYSTEM",
                "status": "SUCCESS",
                "answer": "대화 이력이 초기화되었습니다.",
                "summary": "대화 이력이 초기화되었습니다.",
            }
        else:
            mode = self.llm.classify_intent(raw)
            clean = raw

        if not clean:
            return {"mode": mode, "status": "ERROR", "detail": "질문 내용이 비어있습니다."}

        if verbose:
            print(f"[ROUTER] mode={mode} | question={clean[:60]}")

        if mode == "CHAT":
            return self.llm.handle_chat(clean, self.memory)

        result = self.rag_engine.ask_rag(clean, role_id=role_id, verbose=verbose)
        result["mode"] = "WORK"
        return result
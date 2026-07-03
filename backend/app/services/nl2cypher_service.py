"""NL→Cypher: LLM генерирует read-only Cypher, сервис его валидирует и выполняет.

Опциональный fallback (settings.nl2cypher_enabled). Безопасность:
запрос выполняется ТОЛЬКО если прошёл _is_read_only() — иначе отклоняется.
"""

from __future__ import annotations

import re

from loguru import logger

from app.config import settings
from app.db.neo4j_client import get_neo4j
from app.prompts import nl2cypher as prompts
from app.services.llm_service import LLMService

# запрещённые (пишущие / опасные) конструкции
_FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|"
    r"CALL\s*\{[^}]*\b(CREATE|MERGE|DELETE|SET)\b|apoc\.\w+\.(create|delete|merge|set|write)|"
    r"gds\.\w+\.write|USING\s+PERIODIC)\b",
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r"^\s*(MATCH|WITH|UNWIND|CALL|RETURN|OPTIONAL)\b", re.IGNORECASE)


def _is_read_only(cypher: str) -> bool:
    if not cypher or not cypher.strip():
        return False
    if not _ALLOWED_START.match(cypher):
        return False
    if _FORBIDDEN.search(cypher):
        return False
    # разрешаем только read-CALL (db.index.fulltext.queryNodes и т.п.)
    for m in re.finditer(r"\bCALL\s+([a-zA-Z0-9_.]+)", cypher, re.IGNORECASE):
        proc = m.group(1).lower()
        if any(w in proc for w in ("write", "create", "delete", "merge", "set", "drop")):
            return False
    return True


def _ensure_limit(cypher: str, row_limit: int) -> str:
    if re.search(r"\blimit\b", cypher, re.IGNORECASE):
        return cypher
    return cypher.rstrip().rstrip(";") + f"\nLIMIT {row_limit}"


class NL2CypherService:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def run(self, question):
        """Возвращает {cypher, rows, ok, error}. Не выполняет запись."""
        if not settings.nl2cypher_enabled:
            return {"ok": False, "error": "nl2cypher disabled", "cypher": None, "rows": []}
        prompt = prompts.build_prompt(question, settings.nl2cypher_row_limit)
        result = await self.llm.generate_json(
            prompt, system=prompts.SYSTEM, model=settings.ollama_model_synth, max_tokens=400,
        )
        cypher = (result or {}).get("cypher") if isinstance(result, dict) else None
        if not cypher:
            return {"ok": False, "error": "no cypher generated", "cypher": None, "rows": []}
        if not _is_read_only(cypher):
            logger.warning(f"nl2cypher rejected non-read-only query: {cypher[:200]}")
            return {"ok": False, "error": "rejected: not read-only", "cypher": cypher, "rows": []}
        cypher = _ensure_limit(cypher, settings.nl2cypher_row_limit)
        try:
            neo = get_neo4j()
            with neo.driver.session() as s:
                rows = [dict(r) for r in s.run(cypher)]
            return {"ok": True, "error": None, "cypher": cypher, "rows": rows[:settings.nl2cypher_row_limit]}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"nl2cypher execution failed: {e}")
            return {"ok": False, "error": str(e)[:200], "cypher": cypher, "rows": []}

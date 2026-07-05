"""LLM-NER: извлекает упоминания материалов/режимов/свойств из чанка документа.

Используется в AutoEnrichmentService после ingest'а нового документа —
создаёт :MENTIONS-рёбра к существующим или новым узлам справочников.

Экономия: используется дешёвая модель (Qwen 3B) с очень коротким промптом.
"""

from __future__ import annotations

import json

from loguru import logger

from app.config import settings
from app.prompts import ner_extractor as ner_prompts
from app.services import dictionary
from app.services.llm_service import LLMService


class NERService:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def extract(self, chunk_text):
        """Возвращает {materials: [{raw, match}], modes, properties}."""
        known_mats = [m["code"] for m in dictionary.all_materials()[:60]]
        known_props = [p["code"] for p in dictionary.all_properties()[:60]]
        prompt = ner_prompts.build_prompt(chunk_text, known_materials=known_mats,
                                          known_properties=known_props)
        result = await self.llm.generate_json(
            prompt, system=ner_prompts.SYSTEM, model=settings.ollama_model_tool,
            max_tokens=400,
        )
        if not result:
            return {"materials": [], "modes": [], "properties": []}
        # нормализуем через словари
        def _norm_list(items, lookup_fn):
            out = []
            for it in items or []:
                if isinstance(it, str):
                    raw = it
                    hit = lookup_fn(it)
                else:
                    raw = it.get("raw") or it.get("name") or ""
                    hit = it.get("match") or lookup_fn(raw)
                if raw:
                    out.append({"raw": raw, "match": hit})
            return out
        return {
            "materials": _norm_list(result.get("materials", []), dictionary.lookup_material),
            "modes": _norm_list(result.get("modes", []), dictionary.lookup_mode),
            "properties": _norm_list(result.get("properties", []), dictionary.lookup_property),
        }

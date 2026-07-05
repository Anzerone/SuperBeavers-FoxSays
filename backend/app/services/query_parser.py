"""QueryParser: вопрос пользователя → QueryIntent (структурированный dict)."""

from __future__ import annotations

from loguru import logger

from app.prompts import query_parser as qp_prompts
from app.services import dictionary
from app.services.llm_service import LLMService


class QueryParser:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def parse(self, question):
        # Собираем подсказки для LLM
        materials_codes = [m["code"] for m in dictionary.all_materials()[:50]]
        property_codes = [p["code"] for p in dictionary.all_properties()[:50]]
        mode_codes = [mo["code"] for mo in dictionary.all_modes()[:50]]
        prompt = qp_prompts.build_prompt(
            question,
            known_materials=materials_codes,
            known_properties=property_codes,
            known_modes=mode_codes,
        )
        result = await self.llm.generate_json(prompt, system=qp_prompts.SYSTEM)
        if not result:
            # fallback: тривиальный парсинг через словари
            result = self._fallback_parse(question)
        # Пост-обработка: нормализуем match через словари
        for m in result.get("materials") or []:
            if not m.get("match"):
                hit = dictionary.lookup_material(m.get("raw", ""))
                if hit:
                    m["match"] = hit
        for p in result.get("properties") or []:
            if not p.get("match"):
                hit = dictionary.lookup_property(p.get("raw", ""))
                if hit:
                    p["match"] = hit

        # Ключевые слова для intent — надёжнее, чем LLM. Вопросы «Обзор…» /
        # «Литературный обзор…» / «Мировая практика» / «Отечественная и
        # зарубежная практика» — это literature_review, что бы LLM ни ответил.
        low = (question or "").lower()
        if any(k in low for k in (
            "литературный обзор", "литобзор", "обзор ",
            "мировая практика", "зарубежная практика",
            "отечественная и мировая", "обзор технических решений",
        )):
            result["intent"] = "literature_review"
        elif any(k in low for k in ("сравни ", "сравнени", "vs ", " или ",
                                    "технико-экономическ", "по сравнению")):
            if result.get("intent") != "literature_review":
                result["intent"] = "comparison"
        return result

    def _fallback_parse(self, question):
        """Если LLM недоступна — простой словарный матчинг."""
        text = question.lower()
        materials = []
        for m in dictionary.all_materials():
            for key in [m["display_name"]] + (m.get("aliases") or []):
                if key.lower() in text:
                    materials.append({"raw": key, "match": m["code"]})
                    break
        properties = []
        for p in dictionary.all_properties():
            for key in [p["display_name"]] + (p.get("aliases") or []):
                if key.lower() in text:
                    properties.append({"raw": key, "match": p["code"]})
                    break
        return {
            "intent": "experiment_lookup",
            "materials": materials,
            "modes": [],
            "properties": properties,
            "equipment": [],
            "authors": [],
            "teams": [],
            "time_range": None,
            "tags": [],
            "open_questions": [],
        }

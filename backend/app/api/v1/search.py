"""API: /api/v1/search/autocomplete — поиск по локальным словарям."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import dictionary

router = APIRouter()


@router.get("/autocomplete")
async def autocomplete(q: str = Query(..., min_length=1), type: str = Query("all")):
    """type: material | property | mode | equipment | all."""
    q_low = q.lower()

    def _match(items):
        out = []
        for it in items:
            hay = " ".join([it.get("display_name") or ""] + (it.get("aliases") or []))
            if q_low in hay.lower():
                out.append({
                    "code": it["code"],
                    "display_name": it["display_name"],
                    "aliases": it.get("aliases", [])[:3],
                })
            if len(out) >= 8:
                break
        return out

    if type == "material":
        return {"suggestions": _match(dictionary.all_materials())}
    if type == "property":
        return {"suggestions": _match(dictionary.all_properties())}
    if type == "mode":
        return {"suggestions": _match(dictionary.all_modes())}
    if type == "equipment":
        return {"suggestions": _match(dictionary.all_equipment())}
    return {
        "materials": _match(dictionary.all_materials()),
        "properties": _match(dictionary.all_properties()),
        "modes": _match(dictionary.all_modes()),
        "equipment": _match(dictionary.all_equipment()),
    }


class NlCypherRequest(BaseModel):
    question: str


@router.post("/nl2cypher")
async def nl2cypher(req: NlCypherRequest):
    """Опциональный NL→Cypher (read-only). Включается settings.nl2cypher_enabled."""
    from app.services.llm_service import LLMService
    from app.services.nl2cypher_service import NL2CypherService
    llm = LLMService()
    try:
        return await NL2CypherService(llm).run(req.question)
    finally:
        await llm.close()

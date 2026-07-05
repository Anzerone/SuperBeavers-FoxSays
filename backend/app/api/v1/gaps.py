"""API: /api/v1/gaps — data-gaps + structural-gaps."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.prompts import gap_hypothesis
from app.services import dictionary
from app.services.gaps_service import GapsService
from app.services.llm_service import LLMService, user_request_gate

router = APIRouter()


@router.get("/data")
async def data_gaps(property: str | None = Query(None), top_materials: int = 15):
    svc = GapsService()
    return svc.data_gaps_matrix(property_code=property, top_materials=top_materials)


@router.get("/structural")
async def structural_gaps(limit: int = 30):
    svc = GapsService()
    return {"pairs": svc.structural_gaps(limit=limit)}


class HypothesisRequest(BaseModel):
    material: str
    # оси поменялись: теперь process (Mode.category), а не температурный бакет
    process: str | None = None
    mode_bucket: str | None = None   # оставляем как алиас на переходный период
    property: str


def _gather_hypothesis_context(material_code, process):
    """Из графа собираем контекст, чтобы LLM не отвечал шаблоном:
    - соседние клетки: какие процессы уже применяли к этому материалу;
    - факты о материале: имя, семейство, базовый элемент, число упоминаний.
    Возвращает (material_dict, facts_list, neighbors_list)."""
    from app.db.neo4j_client import get_neo4j
    facts = []
    neighbors = []
    material = {"code": material_code, "display_name": material_code}
    try:
        with get_neo4j().driver.session() as s:
            rec = s.run(
                "MATCH (m:Material {code:$c}) "
                "RETURN m.display_name AS n, m.family AS fam, m.base_element AS be",
                c=material_code,
            ).single()
            if rec:
                material["display_name"] = rec["n"] or material_code
                if rec["fam"]:
                    material["family"] = rec["fam"]
                if rec["be"]:
                    material["base_element"] = rec["be"]

            # Соседние клетки: другие процессы, применённые к этому материалу
            recs = s.run(
                """
                MATCH (m:Material {code:$c})<-[:USED_MATERIAL]-(e:Experiment)
                      -[:USED_MODE]->(mo:Mode)
                WITH coalesce(mo.category, mo.display_name, mo.code) AS proc,
                     count(DISTINCT e) AS n
                WHERE proc IS NOT NULL AND proc <> $skip
                RETURN proc, n ORDER BY n DESC LIMIT 8
                """,
                c=material_code, skip=process,
            )
            for r in recs:
                neighbors.append(f"{material['display_name']} × {r['proc']} (n={r['n']})")

            # Какие свойства меряли на этом материале
            recs = s.run(
                """
                MATCH (m:Material {code:$c})<-[:USED_MATERIAL]-(e:Experiment)
                      -[:MEASURED]->(p:Property)
                RETURN coalesce(p.display_name, p.code) AS name, count(DISTINCT e) AS n
                ORDER BY n DESC LIMIT 5
                """, c=material_code,
            )
            for r in recs:
                facts.append(f"измерено: {r['name']} (в {r['n']} эксп.)")
    except Exception:  # noqa: BLE001
        pass
    return material, facts, neighbors


@router.post("/hypothesis")
async def hypothesis(req: HypothesisRequest):
    llm = LLMService()
    mat, facts, neighbors = _gather_hypothesis_context(
        req.material, req.process or req.mode_bucket or "неизвестный процесс",
    )
    # Если есть словарная запись — она надёжнее, чем то что мы вытянули из графа
    dict_entry = dictionary.get_material(req.material)
    if dict_entry:
        mat.update({k: v for k, v in dict_entry.items() if v})
    prop = dictionary.get_property(req.property) or {"code": req.property, "display_name": req.property}
    process = req.process or req.mode_bucket or "неизвестный процесс"
    prompt = gap_hypothesis.build_prompt(mat, process, prop,
                                          neighbors=neighbors, material_facts=facts)

    async def stream():
        user_request_gate.enter()
        try:
            async for tok in llm.generate_stream(prompt, system=gap_hypothesis.SYSTEM):
                safe = tok.replace("\r", "").replace("\n", "\\n")
                yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            user_request_gate.exit()
            await llm.close()

    return StreamingResponse(stream(), media_type="text/event-stream")

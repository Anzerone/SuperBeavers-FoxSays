"""API: /api/v1/explorer/{entity_type}/{code} — эго-сеть узла + связанные + файл."""

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.db.neo4j_client import get_neo4j
from app.services.graph_service import GraphService, list_related

router = APIRouter()

TYPE_TO_LABEL = {
    "material": "Material", "property": "Property", "mode": "Mode",
    "equipment": "Equipment", "experiment": "Experiment",
    "author": "Author", "team": "Team", "document": "Document",
    "conclusion": "Conclusion", "tag": "Tag",
}


def _resolve_label(entity_type):
    label = TYPE_TO_LABEL.get(entity_type.lower())
    if not label:
        raise HTTPException(status_code=400, detail=f"Unknown entity type: {entity_type}")
    return label


@router.get("/list/{entity_type}")
async def list_entities(entity_type: str, limit: int = Query(200, ge=1, le=2000)):
    """Плоский список сущностей одного типа для выпадашек фронта.
    Возвращает [{code, title}] отсортированные по title."""
    from app.db.neo4j_client import get_neo4j
    label = _resolve_label(entity_type)
    key_map = {
        "Material": "code", "Mode": "code", "Property": "code", "Equipment": "code",
        "Tag": "code", "Author": "author_id", "Team": "team_id",
        "Document": "doc_id", "Experiment": "experiment_id", "Conclusion": "conclusion_id",
    }
    key = key_map.get(label)
    if not key:
        raise HTTPException(status_code=400, detail=f"list not supported for {entity_type}")
    # Фильтруем откровенно мусорные варианты, которые попали через LLM-
    # экстрактор без словаря: сырые PROP-EXT-/MAT-EXT-/MODE-EXT- коды в поле
    # title, служебные фразы «не определено», пустые/из одного символа названия.
    # Также прячем сущности вообще без связей — в UI толку от них нет.
    q = f"""
    MATCH (n:{label})
    WITH n, coalesce(n.display_name, n.title, n.full_name, n.{key}) AS title,
             size([(n)--() | 1]) AS deg
    WHERE title IS NOT NULL
      AND size(trim(title)) >= 2
      AND NOT toLower(trim(title)) IN ['не определено','не определен','unknown','none','n/a','-','—']
      AND NOT title =~ '^(MAT|MODE|PROP|EXP|DOC|CONC|EQ|MODE)-.*'
      AND deg > 0
    RETURN n.{key} AS code, title, deg
    ORDER BY deg DESC, title
    LIMIT $lim
    """
    with get_neo4j().driver.session() as s:
        items = [{"code": r["code"], "title": r["title"], "count": r["deg"]}
                 for r in s.run(q, lim=int(limit))]
    return {"items": items}


@router.get("/document/{doc_id}/file")
async def document_file(doc_id: str, inline: bool = Query(True)):
    """Отдаёт файл документа по doc_id. Путь берётся из Neo4j (Document.file_path).
    inline=true — попытка открыть в браузере (PDF); false — скачать."""
    with get_neo4j().driver.session() as s:
        rec = s.run(
            "MATCH (d:Document {doc_id:$id}) RETURN d.file_path AS p, d.title AS t",
            id=doc_id,
        ).single()
    if not rec or not rec["p"]:
        raise HTTPException(status_code=404, detail="Документ не найден")
    path = rec["p"]
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Файл на диске отсутствует: {path}")
    filename = Path(path).name
    ctype, _ = mimetypes.guess_type(filename)
    disposition = "inline" if inline else "attachment"
    # HTTP-заголовки — latin-1; для кириллицы filename нужен RFC 5987 (filename*=UTF-8''…)
    from urllib.parse import quote
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii")
    header = (
        f"{disposition}; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return FileResponse(
        path,
        media_type=ctype or "application/octet-stream",
        headers={"Content-Disposition": header},
    )


@router.get("/{entity_type}/{code}")
async def explorer(entity_type: str, code: str, depth: int = Query(2, ge=1, le=3)):
    label = _resolve_label(entity_type)
    svc = GraphService()
    return svc.fetch_around(label, code, depth=depth)


@router.get("/{entity_type}/{code}/related")
async def related(entity_type: str, code: str, limit: int = Query(20, ge=1, le=100)):
    """Плоский список связанных сущностей одного узла — по одному вызову
    получаем «покажи всё, что связано с этим экспериментом/лабораторией/автором».
    Возвращает пары (related_type, code, title, relation, weight)."""
    label = _resolve_label(entity_type)
    return {"items": list_related(label, code, limit=limit)}

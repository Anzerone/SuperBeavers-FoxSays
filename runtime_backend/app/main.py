import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models import AskRequest, IngestRequest
from app.services.ingest import ingest_service
from app.services.query_parser import parse_query
from app.services.repository import repository

settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "data_mode": settings.data_mode,
        "neo4j_enabled": settings.neo4j_enabled,
        "qdrant_enabled": settings.qdrant_enabled,
        "llm_enabled": settings.llm_enabled,
    }


@app.post(f"{settings.api_prefix}/ask")
def ask(payload: AskRequest):
    intent = parse_query(payload.question, geography=payload.geography, years=payload.years)
    return repository.ask(payload.question, intent, verified_only=payload.verified_only)


@app.post(f"{settings.api_prefix}/ask/stream")
def ask_stream(payload: AskRequest):
    intent = parse_query(payload.question, geography=payload.geography, years=payload.years)
    response = repository.ask(payload.question, intent, verified_only=payload.verified_only)

    async def events():
        yield f"event: intent\ndata: {intent.model_dump_json()}\n\n"
        yield f"event: subgraph\ndata: {json.dumps({'nodes': [node.model_dump() for node in response.nodes], 'edges': [edge.model_dump() for edge in response.edges], 'meta': response.graph_insights}, ensure_ascii=False)}\n\n"
        for chunk in response.answer.split(". "):
            yield f"event: token\ndata: {chunk.strip()}\n\n"
        yield f"event: sources\ndata: {json.dumps([item.model_dump() for item in response.evidence], ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get(f"{settings.api_prefix}/experiments/" + "{experiment_id}")
def experiment(experiment_id: str):
    item = repository.experiment(experiment_id)
    if not item:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return item


@app.get(f"{settings.api_prefix}/explorer/" + "{entity_type}/{code}")
def explorer(entity_type: str, code: str, depth: int = Query(default=1, ge=1, le=3)):
    intent = parse_query(code)
    response = repository.ask(code, intent, verified_only=False)
    return {"entity_type": entity_type, "code": code, "depth": depth, "nodes": response.nodes, "edges": response.edges}


@app.get(f"{settings.api_prefix}/gaps")
def gaps():
    return repository.gaps()


@app.get(f"{settings.api_prefix}/timeline")
def timeline(material: str | None = None, property: str | None = None):
    return {"points": repository.timeline(material=material, property_name=property)}


@app.get(f"{settings.api_prefix}/search/autocomplete")
def autocomplete(q: str = "", type: str | None = None):
    return {"items": repository.autocomplete(q, type)}


@app.post(f"{settings.api_prefix}/admin/load")
def load(payload: IngestRequest, background_tasks: BackgroundTasks):
    corpus_dir = Path(payload.corpus_dir) if payload.corpus_dir else settings.corpus_dir
    limit = payload.limit or settings.ingest_limit
    background_tasks.add_task(ingest_service.load, corpus_dir, limit, payload.reset)
    return {"state": "scheduled", "corpus_dir": str(corpus_dir), "limit": limit}


@app.get(f"{settings.api_prefix}/admin/status")
def load_status():
    return ingest_service.status

"""API: /api/v1/admin — загрузка корпуса, обогащение, извлечение, метрики."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.services.auto_enrichment import AutoEnrichmentService
from app.services.ingest_service import IngestService
from app.services.llm_service import LLMService
from app.services.ner_service import NERService
from app.services.rag_service import RAGService

router = APIRouter()

# In-memory статус
_STATUS = {"stage": "idle", "progress": 0, "stats": None, "started_at": None, "finished_at": None}
_METRICS = {
    "ingest_seconds": None,
    "avg_tokens_per_question": None,
    "avg_latency_ms": None,
    "questions_answered": 0,
}
_ENRICHMENT_EVENTS = []


class LoadRequest(BaseModel):
    path: str | None = None
    urls: list[str] | None = None


def _run_ingest(path):
    global _STATUS
    _STATUS.update(stage="loading", progress=0, started_at=time.time())
    try:
        ingest = IngestService()
        stats = ingest.load_corpus(path or settings.corpus_dir)
        _STATUS.update(stage="done", progress=100, stats=stats,
                       finished_at=time.time())
        _METRICS["ingest_seconds"] = round(_STATUS["finished_at"] - _STATUS["started_at"], 1)
    except Exception as e:
        logger.exception("ingest failed")
        _STATUS.update(stage="error", stats={"error": str(e)}, finished_at=time.time())


@router.post("/load")
def load(req: LoadRequest, background: BackgroundTasks):
    if _STATUS["stage"] == "loading":
        raise HTTPException(status_code=409, detail="ingest already in progress")
    background.add_task(_run_ingest, req.path)
    return {"queued": True}


@router.get("/status")
def status():
    return _STATUS


@router.get("/metrics")
def metrics():
    return _METRICS


@router.get("/enrichment/events")
def enrichment_events(limit: int = 100):
    return {"events": _ENRICHMENT_EVENTS[-limit:]}


class EnrichRequest(BaseModel):
    scope: str = "new"   # 'all' или 'new'


@router.post("/enrich")
async def enrich(req: EnrichRequest):
    """Ручной запуск обогащения. Возвращает список событий."""
    llm = LLMService()
    rag = RAGService()
    ner = NERService(llm)
    enricher = AutoEnrichmentService(llm, rag, ner)
    try:
        # Для сжатого MVP: пересчитываем PageRank + Louvain + структурные пробелы.
        enricher.refresh_pagerank_and_communities()
        predictions = enricher.link_predictor(sample=50)
        _ENRICHMENT_EVENTS.extend(enricher.events)
        return {"events": enricher.events, "predictions_count": len(predictions)}
    finally:
        await llm.close()


class ExtractRequest(BaseModel):
    scope: str = "new"          # 'all' | 'new'
    limit: int | None = None    # максимум документов за проход


_EXTRACT_STATUS = {"stage": "idle", "stats": None, "started_at": None, "finished_at": None}


async def _run_extract(scope, limit):
    from app.services.doc_extraction_service import DocExtractionService
    _EXTRACT_STATUS.update(stage="running", started_at=time.time(), stats=None)
    llm = LLMService()
    rag = RAGService()
    ner = NERService(llm)
    extractor = DocExtractionService(llm, rag, ner)
    try:
        result = await extractor.extract_all(limit=limit, scope=scope)
        _ENRICHMENT_EVENTS.extend(extractor.events[-200:])
        _EXTRACT_STATUS.update(stage="done", stats=result["stats"], finished_at=time.time())
    except Exception as e:  # noqa: BLE001
        logger.exception("doc extraction failed")
        _EXTRACT_STATUS.update(stage="error", stats={"error": str(e)}, finished_at=time.time())
    finally:
        await llm.close()


@router.post("/extract")
async def extract(req: ExtractRequest, background: BackgroundTasks):
    """Фаза 2: извлечение экспериментов/связей из уже загруженных документов.

    Работает по документам в графе (NER → :MENTIONS, LLM → :Experiment/:Conclusion).
    Без Ollama LLM-шаг пропускается, остаётся словарный NER.
    """
    if _EXTRACT_STATUS["stage"] == "running":
        raise HTTPException(status_code=409, detail="extraction already in progress")
    background.add_task(_run_extract, req.scope, req.limit)
    return {"queued": True, "scope": req.scope}


@router.get("/extract/status")
def extract_status():
    return _EXTRACT_STATUS


@router.get("/stats")
def stats():
    """Сводная витрина графа (узлы/рёбра/документы/гео) + метрики кэшей."""
    from app.services.graph_service import graph_stats
    from app.services.cache_service import answer_cache
    st = graph_stats()
    st["answer_cache"] = answer_cache.stats()
    return st

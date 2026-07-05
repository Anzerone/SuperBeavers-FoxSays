"""API: /api/v1/admin — загрузка корпуса, обогащение, извлечение, метрики."""

from __future__ import annotations

import asyncio
import time

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
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
        # Авто-обогащение useful_info-сниппетов после загрузки. Выполняется
        # в этом же background-треде через asyncio.run — UI уже увидел
        # /status=done по ingest, а enrich идёт своим статусом.
        if settings.useful_info_enrich_on_ingest and _ENRICH_STATUS["stage"] != "running":
            try:
                asyncio.run(_run_useful_info_enrich(None))
            except Exception:  # noqa: BLE001
                logger.exception("post-ingest useful_info enrich failed")
    except Exception as e:
        logger.exception("ingest failed")
        _STATUS.update(stage="error", stats={"error": str(e)}, finished_at=time.time())


@router.post("/load")
def load(req: LoadRequest, background: BackgroundTasks):
    if _STATUS["stage"] == "loading":
        raise HTTPException(status_code=409, detail="ingest already in progress")
    background.add_task(_run_ingest, req.path)
    return {"queued": True}


@router.post("/corpus/upload")
async def corpus_upload(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    autoload: bool = True,
):
    """Загрузка файлов в корпус: multipart-форма → data/corpus/uploads/.
    Имена санитизируются (basename). Если autoload=true (дефолт) и ingest
    сейчас не идёт — сразу же ставим в очередь загрузку всего corpus_dir,
    чтобы новые файлы попали в БД без второго клика."""
    dest = Path(settings.corpus_dir) / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    skipped = []
    allowed = {ext.lower() for ext in settings.doc_extensions}
    for f in files:
        raw_name = f.filename or "unnamed"
        # basename отсечёт "..\..\etc\passwd" и любые path-traversal попытки
        name = Path(raw_name).name
        if not name:
            skipped.append({"name": raw_name, "reason": "empty name"})
            continue
        if allowed and Path(name).suffix.lower() not in allowed:
            skipped.append({"name": name, "reason": "unsupported extension"})
            continue
        target = dest / name
        # если файл с таким же именем уже есть — добавляем суффикс _1, _2, ...
        if target.exists():
            stem, suf = target.stem, target.suffix
            i = 1
            while (dest / f"{stem}_{i}{suf}").exists():
                i += 1
            target = dest / f"{stem}_{i}{suf}"
        try:
            content = await f.read()
            target.write_bytes(content)
            saved.append(str(target.relative_to(settings.corpus_dir)))
        except Exception as e:  # noqa: BLE001
            logger.exception(f"upload failed for {name}")
            skipped.append({"name": name, "reason": str(e)[:200]})

    triggered_ingest = False
    if autoload and saved and _STATUS["stage"] != "loading":
        background.add_task(_run_ingest, settings.corpus_dir)
        triggered_ingest = True

    return {
        "saved": saved,
        "skipped": skipped,
        "count": len(saved),
        "dir": str(dest),
        "ingest_queued": triggered_ingest,
    }


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
async def enrich(req: EnrichRequest, background: BackgroundTasks):
    """Ручной запуск обогащения. Возвращает список событий.

    Помимо PageRank/Louvain/link_predictor запускает в фоне LLM-обогащение
    useful_info-сниппетов (кнопка «Обогатить» на UI): если есть черновые
    Experiment с source='useful_info' без структурных связей — они уходят
    на модель из OLLAMA_MODEL_ENRICH (fallback: OLLAMA_MODEL_EXTRACT/tool).
    """
    llm = LLMService()
    rag = RAGService()
    ner = NERService(llm)
    enricher = AutoEnrichmentService(llm, rag, ner)
    try:
        enricher.refresh_pagerank_and_communities()
        predictions = enricher.link_predictor(sample=50)
        _ENRICHMENT_EVENTS.extend(enricher.events)
        ui_enrich_queued = False
        if _ENRICH_STATUS["stage"] != "running":
            background.add_task(_run_useful_info_enrich, None)
            ui_enrich_queued = True
        return {
            "events": enricher.events,
            "predictions_count": len(predictions),
            "useful_info_enrich_queued": ui_enrich_queued,
        }
    finally:
        await llm.close()


class ExtractRequest(BaseModel):
    scope: str = "new"          # 'all' | 'new'
    limit: int | None = None    # максимум документов за проход


_EXTRACT_STATUS = {"stage": "idle", "stats": None, "started_at": None, "finished_at": None}
_EXTRACT_CANCEL = False


async def _run_extract(scope, limit):
    global _EXTRACT_CANCEL
    from app.services.doc_extraction_service import DocExtractionService
    _EXTRACT_CANCEL = False
    _EXTRACT_STATUS.update(stage="running", started_at=time.time(), stats=None,
                           finished_at=None)
    llm = LLMService()
    rag = RAGService()
    ner = NERService(llm)
    extractor = DocExtractionService(llm, rag, ner)
    try:
        result = await extractor.extract_all(
            limit=limit, scope=scope,
            should_cancel=lambda: _EXTRACT_CANCEL,
        )
        _ENRICHMENT_EVENTS.extend(extractor.events[-200:])
        stage = "cancelled" if result.get("cancelled") else "done"
        _EXTRACT_STATUS.update(stage=stage, stats=result["stats"], finished_at=time.time())
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


@router.post("/extract/cancel")
def extract_cancel():
    global _EXTRACT_CANCEL
    if _EXTRACT_STATUS["stage"] != "running":
        return {"cancelled": False, "reason": "not running"}
    _EXTRACT_CANCEL = True
    return {"cancelled": True}


class UsefulInfoEnrichRequest(BaseModel):
    limit: int | None = None


_ENRICH_STATUS = {"stage": "idle", "stats": None, "started_at": None, "finished_at": None}
_ENRICH_CANCEL = False


async def _run_useful_info_enrich(limit):
    global _ENRICH_CANCEL
    from app.services.doc_extraction_service import DocExtractionService
    _ENRICH_CANCEL = False
    _ENRICH_STATUS.update(stage="running", started_at=time.time(), stats=None,
                          finished_at=None)
    llm = LLMService()
    rag = RAGService()
    ner = NERService(llm)
    extractor = DocExtractionService(llm, rag, ner)
    try:
        result = await extractor.enrich_useful_info_experiments(
            limit=limit,
            should_cancel=lambda: _ENRICH_CANCEL,
        )
        _ENRICHMENT_EVENTS.extend(extractor.events[-200:])
        stage = "cancelled" if result.get("cancelled") else "done"
        _ENRICH_STATUS.update(stage=stage, stats=result["stats"], finished_at=time.time())
    except Exception as e:  # noqa: BLE001
        logger.exception("useful_info enrich failed")
        _ENRICH_STATUS.update(stage="error", stats={"error": str(e)}, finished_at=time.time())
    finally:
        await llm.close()


@router.post("/useful_info/enrich")
async def useful_info_enrich(req: UsefulInfoEnrichRequest, background: BackgroundTasks):
    """Прогоняет черновые useful_info-эксперименты через OLLAMA_MODEL_ENRICH:
    достраивает USED_MATERIAL / USED_MODE / MEASURED / RESULTED_IN на
    существующих Experiment-узлах, ничего нового не создаёт (кроме Conclusion).
    """
    if _ENRICH_STATUS["stage"] == "running":
        raise HTTPException(status_code=409, detail="enrichment already in progress")
    background.add_task(_run_useful_info_enrich, req.limit)
    return {"queued": True, "limit": req.limit}


@router.get("/useful_info/enrich/status")
def useful_info_enrich_status():
    return _ENRICH_STATUS


@router.post("/useful_info/enrich/cancel")
def useful_info_enrich_cancel():
    global _ENRICH_CANCEL
    if _ENRICH_STATUS["stage"] != "running":
        return {"cancelled": False, "reason": "not running"}
    _ENRICH_CANCEL = True
    return {"cancelled": True}


@router.get("/stats")
def stats():
    """Сводная витрина графа (узлы/рёбра/документы/гео) + метрики кэшей."""
    from app.services.graph_service import graph_stats
    from app.services.cache_service import answer_cache
    st = graph_stats()
    st["answer_cache"] = answer_cache.stats()
    return st


@router.get("/data_quality")
def data_quality():
    """Осмысленные метрики: покрытие экстракции, обогащение useful_info,
    распределение confidence, доля EN/RU в описаниях. Для дашборда админки."""
    from app.services.graph_service import data_quality_summary
    return data_quality_summary()


@router.get("/eval")
def eval_endpoint():
    """ML-baseline: extraction P/R (или coverage), retrieval MRR/nDCG@10,
    SIMILAR_TO ROC-AUC. Для отчёта «модель работает лучше рандома»."""
    from app.services.eval_service import run_full_eval
    return run_full_eval()


@router.post("/normalize/materials")
def normalize_materials(dry_run: bool = False):
    """Однократный проход по MAT-EXT-*: подтягивает display_name/description из
    словаря, склеивает синонимичные автокоды через SUPERSEDED_BY. UI после этого
    показывает «Медь металлическая» вместо «MAT-CU-METAL» в матрице пробелов.
    """
    from app.services.normalize_service import NormalizeService
    return NormalizeService().normalize_materials(dry_run=dry_run)


@router.post("/versioning/apply")
def versioning_apply():
    """Проставить valid_from на MEASURED и разметить актуальные версии.
    После этого /api/v1/versions/{material}/{property} отдаёт историю версий."""
    from app.services.versioning_service import VersioningService
    return VersioningService().apply()


@router.post("/snapshot/dump")
def snapshot_dump():
    """Сохраняет текущий Neo4j+Qdrant в data/snapshots/ для быстрого
    восстановления на других машинах. Итоговые файлы: neo4j.cypher.gz и
    qdrant_*.jsonl.gz — их можно закоммитить (Git LFS) или залить в релиз."""
    from app.services.snapshot_service import SnapshotService, SNAPSHOT_DIR
    try:
        SnapshotService().dump()
        files = sorted(str(p.name) for p in SNAPSHOT_DIR.iterdir())
        return {"ok": True, "snapshot_dir": str(SNAPSHOT_DIR), "files": files}
    except Exception as e:  # noqa: BLE001
        logger.exception("snapshot dump failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot/restore")
def snapshot_restore():
    """Восстанавливает БД из data/snapshots/. Использует ту же логику,
    что и autoingest на старте — вызывать вручную имеет смысл после ручной
    очистки БД."""
    from app.services.snapshot_service import SnapshotService, snapshot_exists
    if not snapshot_exists():
        raise HTTPException(status_code=404, detail="snapshot not found")
    ok = SnapshotService().restore()
    return {"ok": ok}

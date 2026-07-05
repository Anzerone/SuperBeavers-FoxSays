"""FastAPI entrypoint — Норникель AI Science Hack 2026."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1 import (
    admin, ask, auth, compare, explain, explorer, export, gaps, search, versions,
)
from app.config import settings
from app.db.neo4j_client import close_neo4j, get_neo4j, init_neo4j
from app.db.qdrant_client import close_qdrant, init_qdrant
from app.services import auth_service

logger.remove()
logger.add(sys.stderr, level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Научный клубок backend...")
    init_neo4j()
    try:
        get_neo4j().apply_schema()
        logger.info("Neo4j schema applied")
    except Exception as e:
        logger.warning(f"Schema apply failed: {e}")
    try:
        init_qdrant()
    except Exception as e:
        logger.warning(f"Qdrant init failed: {e}")
    try:
        auth_service.init_auth()
    except Exception as e:
        logger.warning(f"Auth init failed: {e}")
    try:
        from app.services import dictionary
        # dicts могут лежать рядом с корпусом (CORPUS_DIR/dicts) или в общем /data/corpus/dicts,
        # если CORPUS_DIR указывает на подкаталог с документами.
        for p in (settings.corpus_dir + "/dicts", "/data/corpus/dicts"):
            import os
            if os.path.isdir(p):
                dictionary.load_dictionaries(p)
                break
    except Exception as e:
        logger.warning(f"Dictionaries not preloaded: {e}")
    # Автоингест «из коробки»: если БД пуста и включён флаг —
    # прогреваем корпус в фоне, чтобы не тормозить старт API.
    try:
        _maybe_autoingest()
    except Exception as e:
        logger.warning(f"Auto-ingest not scheduled: {e}")
    yield
    close_neo4j()
    close_qdrant()


app = FastAPI(
    title="Научный клубок API",
    description="Норникель AI Science Hack 2026 — knowledge graph + Q&A + self-expanding",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(ask.router, prefix="/api/v1/ask", tags=["ask"])
app.include_router(gaps.router, prefix="/api/v1/gaps", tags=["gaps"])
app.include_router(explorer.router, prefix="/api/v1/explorer", tags=["explorer"])
app.include_router(search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(explain.router, prefix="/api/v1/explain", tags=["explain"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(compare.router, prefix="/api/v1/compare", tags=["compare"])
app.include_router(export.router, prefix="/api/v1/export", tags=["export"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(versions.router, prefix="/api/v1/versions", tags=["versions"])


def _corpus_is_empty():
    """True, если в Neo4j нет ни Document, ни Experiment."""
    try:
        with get_neo4j().driver.session() as s:
            rec = s.run(
                "MATCH (n) WHERE n:Document OR n:Experiment "
                "RETURN count(n) AS c LIMIT 1"
            ).single()
            return int((rec or {}).get("c", 0)) == 0
    except Exception as e:
        logger.warning(f"Cannot probe corpus state: {e}")
        return False


def _maybe_autoingest():
    if not settings.auto_ingest_on_startup:
        return

    empty = _corpus_is_empty()

    # 1) Быстрый путь: восстановить из snapshot'а, если он лежит в data/snapshots/.
    #    Так «свежий клон + docker compose up» даёт готовую БД за секунды.
    if empty:
        try:
            from app.services.snapshot_service import SnapshotService, snapshot_exists
            if snapshot_exists():
                logger.info("Auto-ingest: snapshot found, restoring instead of re-ingesting")
                if SnapshotService().restore():
                    return
        except Exception as e:
            logger.warning(f"Snapshot restore failed, falling back to full ingest: {e}")

    # 2) Медленный путь: полный ингест корпуса в фоне. Работает и на пустой БД,
    #    и в «resume mode» — IngestService сам пропустит уже загруженные документы
    #    по file_path, так что рестарт после краша продолжит с того же места.
    if not empty:
        logger.info("Auto-ingest: corpus partially loaded — starting in resume mode")

    import threading

    def _run():
        try:
            from app.services.ingest_service import IngestService
            logger.info(f"Auto-ingest starting: {settings.corpus_dir}")
            stats = IngestService().load_corpus(settings.corpus_dir)
            logger.info(
                f"Auto-ingest done: {stats.get('documents')} документов, "
                f"{stats.get('chunks')} чанков, {stats.get('experiments')} экспериментов"
            )
        except Exception as e:
            logger.exception(f"Auto-ingest failed: {e}")

    threading.Thread(target=_run, name="auto-ingest", daemon=True).start()
    logger.info("Auto-ingest scheduled in background thread")


@app.get("/")
async def root():
    return {
        "name": "Научный клубок API", "version": "0.4.0",
        "features": [
            "Q&A", "gaps", "explorer", "compare",
            "export (MD/JSON-LD/PDF)", "auth+roles", "audit", "versioning",
            "geo-filter (RU/foreign)", "numeric ranges",
        ],
    }


@app.get("/health")
async def health():
    st = {"backend": "ok", "neo4j": "unknown", "qdrant": "unknown"}
    try:
        with get_neo4j().driver.session() as s:
            s.run("RETURN 1").single()
        st["neo4j"] = "ok"
    except Exception as e:
        st["neo4j"] = f"error: {e}"
    try:
        from app.db.qdrant_client import get_qdrant
        get_qdrant().get_collections()
        st["qdrant"] = "ok"
    except Exception as e:
        st["qdrant"] = f"error: {e}"
    return st

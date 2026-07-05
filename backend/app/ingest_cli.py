"""CLI-ингест: загрузка корпуса в ОТДЕЛЬНОМ процессе.

Зачем: обычный /admin/load выполняется внутри того же процесса, что и API,
и тяжёлый разбор PDF (GIL) подвешивает сайт. Здесь ингест идёт отдельным
процессом/контейнером — API остаётся отзывчивым, а прогресс виден в консоли.

Запуск (рекомендуется — отдельный одноразовый контейнер, сайт не трогаем):
    docker compose run --rm backend python -m app.ingest_cli
    docker compose run --rm backend python -m app.ingest_cli /data/corpus_test

Либо отдельным процессом внутри работающего контейнера:
    docker compose exec backend python -m app.ingest_cli
"""

from __future__ import annotations

import sys
import time

from loguru import logger

from app.config import settings
from app.db.neo4j_client import init_neo4j, get_neo4j, close_neo4j
from app.db.qdrant_client import init_qdrant, close_qdrant
from app.services.ingest_service import IngestService


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else settings.corpus_dir
    logger.info(f"=== CLI-ингест начат: {path} ===")
    t0 = time.time()

    init_neo4j()
    try:
        get_neo4j().apply_schema()
        logger.info("Neo4j-схема применена")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"schema apply: {e}")
    try:
        init_qdrant()
        logger.info("Qdrant готов")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"qdrant init: {e}")

    stats = IngestService().load_corpus(path)

    dt = round(time.time() - t0, 1)
    logger.info(
        f"=== ГОТОВО за {dt} c: {stats.get('documents')} документов, "
        f"{stats.get('chunks')} чанков (дедуп {stats.get('chunks_deduped')}), "
        f"{stats.get('archives')} архивов, {len(stats.get('errors') or [])} ошибок ==="
    )
    logger.info(f"По типам: {stats.get('by_type')}")
    close_neo4j()
    close_qdrant()


if __name__ == "__main__":
    main()

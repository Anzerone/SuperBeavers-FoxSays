"""SnapshotService: дамп/восстановление Neo4j + Qdrant в data/snapshots/.

Мотивация: полный ингест корпуса (~5 ГБ) стоит часа времени и токенов на
эмбеддинги Yandex. Один раз запустив ингест на своей машине, разработчик
может сделать snapshot — файлы весят десятки МБ, коммитятся через Git LFS
или лежат в релизах — и коллеги, клонировавшие репо, получают базу
восстановлением за 10-30 секунд.

Формат:
  data/snapshots/
    neo4j.cypher.gz              — CREATE-скрипт (apoc.export.cypher.all)
    qdrant_document_chunks.jsonl.gz  — {id, vector, payload} по строке
    qdrant_experiments_desc.jsonl.gz
    manifest.json                — версия схемы, embedding_dim, дата
"""

from __future__ import annotations

import gzip
import io
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.config import settings
from app.db.neo4j_client import get_neo4j
from app.db.qdrant_client import get_qdrant

SNAPSHOT_DIR = Path("/data/snapshots")
NEO4J_FILE = "neo4j.cypher.gz"
MANIFEST = "manifest.json"


def _q_snapshot_path(collection):
    return SNAPSHOT_DIR / f"qdrant_{collection}.jsonl.gz"


def snapshot_exists():
    return (SNAPSHOT_DIR / MANIFEST).exists() and (SNAPSHOT_DIR / NEO4J_FILE).exists()


class SnapshotService:
    # ---------- DUMP ----------
    def dump(self):
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Snapshot: dumping to {SNAPSHOT_DIR}")
        self._dump_neo4j()
        for c in (settings.qdrant_collection_experiments, settings.qdrant_collection_chunks):
            self._dump_qdrant_collection(c)
        (SNAPSHOT_DIR / MANIFEST).write_text(json.dumps({
            "created_at": datetime.utcnow().isoformat() + "Z",
            "embedding_dim": settings.embedding_dim,
            "embedding_provider": settings.embedding_provider,
            "collections": [
                settings.qdrant_collection_experiments,
                settings.qdrant_collection_chunks,
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Snapshot: done")

    def _dump_neo4j(self):
        # apoc.export.cypher.all умеет писать в stream — забираем строки прямо в gzip.
        out_path = SNAPSHOT_DIR / NEO4J_FILE
        with gzip.open(out_path, "wt", encoding="utf-8") as gz:
            with get_neo4j().driver.session() as s:
                recs = s.run(
                    "CALL apoc.export.cypher.all(null, "
                    "{format:'cypher-shell', streamStatements:true, useOptimizations:{type:'UNWIND_BATCH', unwindBatchSize:100}}) "
                    "YIELD cypherStatements RETURN cypherStatements"
                )
                total = 0
                for r in recs:
                    stmt = r["cypherStatements"]
                    if stmt:
                        gz.write(stmt)
                        gz.write("\n")
                        total += 1
        logger.info(f"Neo4j dumped: {total} batches → {out_path.name}")

    def _dump_qdrant_collection(self, name):
        qc = get_qdrant()
        try:
            qc.get_collection(name)
        except Exception as e:
            logger.warning(f"Qdrant collection {name} missing, skip dump: {e}")
            return
        out = _q_snapshot_path(name)
        total = 0
        with gzip.open(out, "wt", encoding="utf-8") as gz:
            next_page = None
            while True:
                pts, next_page = qc.scroll(
                    collection_name=name, offset=next_page,
                    with_vectors=True, with_payload=True, limit=256,
                )
                for p in pts:
                    row = {"id": str(p.id), "vector": p.vector, "payload": p.payload or {}}
                    gz.write(json.dumps(row, ensure_ascii=False) + "\n")
                    total += 1
                if next_page is None:
                    break
        logger.info(f"Qdrant '{name}' dumped: {total} points → {out.name}")

    # ---------- RESTORE ----------
    def restore(self):
        if not snapshot_exists():
            logger.info("Snapshot: nothing to restore")
            return False
        logger.info(f"Snapshot: restoring from {SNAPSHOT_DIR}")
        manifest = json.loads((SNAPSHOT_DIR / MANIFEST).read_text(encoding="utf-8"))
        if int(manifest.get("embedding_dim") or 0) != int(settings.embedding_dim):
            logger.warning(
                f"Snapshot embedding_dim {manifest.get('embedding_dim')} != "
                f"current {settings.embedding_dim} — skip Qdrant restore"
            )
            skip_q = True
        else:
            skip_q = False
        self._restore_neo4j()
        if not skip_q:
            for c in manifest.get("collections") or []:
                self._restore_qdrant_collection(c)
        logger.info("Snapshot: restore done")
        return True

    def _restore_neo4j(self):
        path = SNAPSHOT_DIR / NEO4J_FILE
        with gzip.open(path, "rt", encoding="utf-8") as gz:
            buf = io.StringIO()
            with get_neo4j().driver.session() as s:
                for line in gz:
                    buf.write(line)
                    # cypher-shell разделяет операторы точкой с запятой в конце строки
                    if line.rstrip().endswith(";"):
                        stmt = buf.getvalue().strip().rstrip(";")
                        buf = io.StringIO()
                        if not stmt or stmt.startswith(":"):
                            continue  # :begin / :commit — командам shell'а тут не место
                        try:
                            s.run(stmt)
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"restore stmt failed: {e} ({stmt[:80]}…)")
        logger.info("Neo4j restored")

    def _restore_qdrant_collection(self, name):
        from qdrant_client.http.models import PointStruct, Distance, VectorParams
        qc = get_qdrant()
        existing = {c.name for c in qc.get_collections().collections}
        if name not in existing:
            qc.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            )
        path = _q_snapshot_path(name)
        if not path.exists():
            logger.info(f"Qdrant snapshot for {name} missing, skip")
            return
        batch = []
        total = 0
        with gzip.open(path, "rt", encoding="utf-8") as gz:
            for line in gz:
                row = json.loads(line)
                batch.append(PointStruct(id=row["id"], vector=row["vector"], payload=row["payload"]))
                if len(batch) >= 256:
                    qc.upsert(collection_name=name, points=batch)
                    total += len(batch)
                    batch = []
        if batch:
            qc.upsert(collection_name=name, points=batch)
            total += len(batch)
        logger.info(f"Qdrant '{name}' restored: {total} points")

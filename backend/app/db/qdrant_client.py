"""Qdrant клиент: 2 коллекции — описания экспериментов и чанки документов."""

from loguru import logger

from app.config import settings

_client = None


def init_qdrant():
    global _client
    if not settings.embeddings_enabled:
        return
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Distance, VectorParams

    _client = QdrantClient(url=settings.qdrant_url, timeout=10)
    existing = {c.name for c in _client.get_collections().collections}
    for name in (settings.qdrant_collection_experiments, settings.qdrant_collection_chunks):
        if name not in existing:
            _client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            )
            logger.info(f"Qdrant collection created: {name}")
    logger.info(f"Qdrant ok: {settings.qdrant_url}")


def get_qdrant():
    if _client is None:
        raise RuntimeError("Qdrant not initialized")
    return _client


def close_qdrant():
    global _client
    if _client:
        _client.close()
        _client = None

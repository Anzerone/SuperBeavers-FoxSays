"""RAGService: эмбеддинги + поиск релевантных чанков документов.

Провайдер эмбеддингов выбирается через settings.embedding_provider:
  * 'yandex' — Yandex Foundation Models (облако, дефолт):
      POST https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding
      modelUri: emb://<folder>/text-search-{doc,query}/latest, dim = 256.
  * 'local'  — fastembed (офлайн-фолбэк), модель из settings.embedding_model.

Для документов (индексация) используется text-search-doc, для запросов —
text-search-query: асимметричная модель, так и задумано у Yandex.
"""

from __future__ import annotations

import hashlib
import time
import uuid

import httpx
from loguru import logger

from app.config import settings


class _YandexEmbedder:
    """Синхронный клиент text-embedding эндпоинта Yandex Foundation Models."""

    URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"

    def __init__(self):
        self.client = httpx.Client(timeout=30.0)

    def _model_uri(self, kind):
        model = (settings.yandex_embedding_model_doc if kind == "doc"
                 else settings.yandex_embedding_model_query)
        return f"emb://{settings.yandex_folder_id}/{model}"

    def _headers(self):
        return {
            "Authorization": f"Api-Key {settings.yandex_api_key}",
            "Content-Type": "application/json",
            "x-folder-id": settings.yandex_folder_id,
        }

    def embed(self, texts, kind="doc"):
        # Yandex embeddings — один текст за запрос. Идём последовательно
        # с бэкоффом на 429, чтобы не биться о rate limit.
        out = []
        for t in texts:
            emb = self._embed_one(t or " ", kind)
            out.append(emb)
        return out

    def _embed_one(self, text, kind):
        body = {"modelUri": self._model_uri(kind), "text": text[:8000]}
        for attempt in range(4):
            try:
                r = self.client.post(self.URL, headers=self._headers(), json=body)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json().get("embedding") or []
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    logger.warning(f"Yandex embedding failed after retries: {e}")
                    return [0.0] * settings.embedding_dim
                time.sleep(0.8 * (attempt + 1))
        return [0.0] * settings.embedding_dim


class _OllamaEmbedder:
    """Ollama's /api/embed — батчевый эндпоинт, крутится на GPU хоста.

    Ollama сам загружает модель (bge-m3, nomic-embed-text и т.п.) один раз
    и держит в VRAM. Батч посылаем целиком — обычно 20-500 текстов за раз.
    """

    def __init__(self):
        self.client = httpx.Client(timeout=120.0)
        self.url = f"{settings.ollama_url}/api/embed"

    def embed(self, texts, kind="doc"):
        # Ollama /api/embed принимает и одиночный prompt, и массив input.
        # Батч 128 = sweet spot для bge-m3 на RTX-класс: ~60 chunks/sec.
        # На 256+ Ollama возвращает 400 (лимит по числу токенов в запросе).
        out = []
        batch_size = 128
        for i in range(0, len(texts), batch_size):
            batch = [t or " " for t in texts[i:i + batch_size]]
            body = {"model": settings.embedding_model, "input": batch}
            try:
                r = self.client.post(self.url, json=body)
                r.raise_for_status()
                embs = r.json().get("embeddings") or []
                out.extend(embs)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Ollama embedding batch failed (i={i}): {e}")
                # чтобы не разрушать выравнивание — пустой вектор на каждый чанк
                out.extend([[0.0] * settings.embedding_dim for _ in batch])
        return out


class RAGService:
    _local_embedder = None
    _yandex_embedder = None
    _ollama_embedder = None

    _local_embedder_failed = False

    @classmethod
    def _get_local_embedder(cls):
        if cls._local_embedder is None:
            if cls._local_embedder_failed:
                # Не долбить fastembed каждый вызов, если инициализация уже упала —
                # иначе получаем «Loading model...» в цикле по каждому чанку.
                raise RuntimeError("local embedder previously failed to init")
            from fastembed import TextEmbedding
            logger.info(f"Loading local embedding model {settings.embedding_model}...")
            try:
                cls._local_embedder = TextEmbedding(model_name=settings.embedding_model)
            except Exception as e:
                cls._local_embedder_failed = True
                logger.error(f"Failed to init local embedder ({settings.embedding_model}): {e}")
                raise
            logger.info("Local embedding model loaded")
        return cls._local_embedder

    @classmethod
    def _get_yandex_embedder(cls):
        if cls._yandex_embedder is None:
            cls._yandex_embedder = _YandexEmbedder()
        return cls._yandex_embedder

    @classmethod
    def _get_ollama_embedder(cls):
        if cls._ollama_embedder is None:
            cls._ollama_embedder = _OllamaEmbedder()
        return cls._ollama_embedder

    def _provider(self):
        return (settings.embedding_provider or "local").lower()

    def embed_texts(self, texts, kind="doc"):
        if not texts:
            return []
        p = self._provider()
        if p == "yandex" and settings.yandex_api_key:
            return self._get_yandex_embedder().embed(texts, kind=kind)
        if p == "ollama":
            return self._get_ollama_embedder().embed(texts, kind=kind)
        return [e.tolist() for e in self._get_local_embedder().embed(texts)]

    def _stable_point_id(self, key):
        h = hashlib.sha1(str(key).encode("utf-8")).digest()
        return str(uuid.UUID(bytes=h[:16]))

    def search_chunks(self, query_text, top_k=5, doc_filter=None):
        """Top-K релевантных чанков документов для текстового запроса."""
        from app.db.qdrant_client import get_qdrant
        [vec] = self.embed_texts([query_text], kind="query")
        flt = None
        if doc_filter:
            from qdrant_client.http.models import Filter, FieldCondition, MatchAny
            flt = Filter(must=[FieldCondition(key="doc_id", match=MatchAny(any=doc_filter))])
        res = get_qdrant().query_points(
            collection_name=settings.qdrant_collection_chunks,
            query=vec,
            limit=top_k,
            query_filter=flt,
        ).points
        return [
            {
                "doc_id": (r.payload or {}).get("doc_id"),
                "page": (r.payload or {}).get("page"),
                "text": (r.payload or {}).get("text", ""),
                "score": float(r.score),
            }
            for r in res
        ]

    def search_similar_experiments(self, query_text, top_k=10):
        """Семантический поиск экспериментов по тексту."""
        from app.db.qdrant_client import get_qdrant
        [vec] = self.embed_texts([query_text], kind="query")
        res = get_qdrant().query_points(
            collection_name=settings.qdrant_collection_experiments,
            query=vec,
            limit=top_k,
            score_threshold=settings.similarity_threshold,
        ).points
        return [
            {
                "experiment_id": (r.payload or {}).get("experiment_id"),
                "title": (r.payload or {}).get("title", ""),
                "score": float(r.score),
            }
            for r in res
        ]

from contextlib import suppress

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import get_settings


class QdrantVectorStore:
    collection_name = "nornickel_documents"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = QdrantClient(url=self.settings.qdrant_url) if self.settings.qdrant_enabled else None

    def ensure_collection(self, vector_size: int = 384) -> None:
        if not self.client:
            return
        collections = self.client.get_collections().collections
        if any(item.name == self.collection_name for item in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


with suppress(Exception):
    vector_store = QdrantVectorStore()


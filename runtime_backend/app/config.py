from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Научный клубок API"
    api_prefix: str = "/api/v1"
    corpus_dir: Path = Path("/data/corpus")
    data_mode: str = "real"
    ingest_limit: int = 80

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "nornickel-password"
    neo4j_enabled: bool = False

    qdrant_url: str = "http://qdrant:6333"
    qdrant_enabled: bool = False

    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    llm_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

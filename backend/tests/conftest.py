"""Тестовый бутстрап.

Тесты loader/cache/nl2cypher проверяют чистую Python-логику и не требуют
Neo4j / Qdrant / Ollama / внешних зависимостей. Чтобы их можно было гонять и в
«тонком» окружении, при отсутствии тяжёлых пакетов подставляются лёгкие стенды:
  * app.config      — если нет pydantic-settings;
  * neo4j, httpx    — если пакеты не установлены (модули импортируют их на верхнем
                      уровне, но тестируемые функции их не вызывают).
В обычном окружении используются настоящие пакеты и конфигурация.
"""

import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _install_stub_config():
    cfg = types.ModuleType("app.config")

    class _Settings:
        # loaders
        chunk_size = 800
        chunk_overlap = 200
        doc_extensions = [".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt"]
        corpus_exclude_dirs = ["dicts", ".__archive_tmp__"]
        corpus_recursive = True
        max_uncompressed_mb = 30000
        max_archive_depth = 4
        soffice_convert = False
        soffice_bin = "libreoffice"
        # CAG-кэш
        chunk_dedup = True
        answer_cache_enabled = True
        answer_cache_ttl_s = 604800
        answer_cache_max = 500
        # FTS / nl2cypher
        fts_seed_enabled = True
        fts_seed_limit = 15
        nl2cypher_enabled = False
        nl2cypher_row_limit = 50
        # прочее, что могут дёрнуть модули
        ollama_model_synth = "stub-synth"
        ollama_model_tool = "stub-tool"
        # LLM provider (Yandex/Ollama)
        llm_enabled = True
        llm_provider = "ollama"
        llm_temperature = 0.2
        llm_max_tokens = 800
        llm_timeout_s = 90.0
        ollama_url = "http://localhost:11434"
        yandex_api_key = ""
        yandex_folder_id = "test-folder"
        yandex_base_url = "https://llm.api.cloud.yandex.net/v1"
        yandex_model_synth = "yandexgpt/latest"
        yandex_model_tool = "yandexgpt-lite/latest"
        graph_max_nodes = 500
        qdrant_collection_chunks = "chunks"
        qdrant_collection_experiments = "exp"

    cfg.settings = _Settings()
    cfg.synth_model = lambda: "stub"
    sys.modules["app.config"] = cfg


def _install_stub_module(name, build):
    try:
        __import__(name)
    except ImportError:
        mod = types.ModuleType(name)
        build(mod)
        sys.modules[name] = mod


try:
    import pydantic_settings  # noqa: F401
except ImportError:
    _install_stub_config()


def _build_neo4j(mod):
    class _Driver:
        def session(self, *a, **k):
            raise RuntimeError("stub neo4j: no real DB in tests")

        def close(self):
            pass

    class GraphDatabase:
        @staticmethod
        def driver(*a, **k):
            return _Driver()

    mod.GraphDatabase = GraphDatabase


def _build_httpx(mod):
    class AsyncClient:
        def __init__(self, *a, **k):
            pass

        async def aclose(self):
            pass

    mod.AsyncClient = AsyncClient


def _build_loguru(mod):
    """loguru тянет С-расширения; в тонком окружении заменяем no-op logger."""
    class _Logger:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    mod.logger = _Logger()


def _build_neo4j_client(mod):
    """app.db.neo4j_client — модуль-обёртка, нужен только чтобы импорт eval_service
    не падал на collect-фазе. Настоящие вызовы Neo4j в _prf/_load_pr_pairs не идут."""
    def get_neo4j():
        raise RuntimeError("stub neo4j_client: no real DB in tests")

    mod.get_neo4j = get_neo4j


_install_stub_module("neo4j", _build_neo4j)
_install_stub_module("httpx", _build_httpx)
_install_stub_module("loguru", _build_loguru)
_install_stub_module("app.db.neo4j_client", _build_neo4j_client)

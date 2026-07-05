"""Конфигурация приложения."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme123"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_experiments: str = "experiments_desc"
    qdrant_collection_chunks: str = "document_chunks"
    embeddings_enabled: bool = True
    # Провайдер эмбеддингов: 'yandex' (облако, дефолт) или 'local' (fastembed).
    # Yandex Foundation Models: text-search-doc + text-search-query, 256 dim.
    embedding_provider: str = "yandex"
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 256
    yandex_embedding_model_doc: str = "text-search-doc/latest"
    yandex_embedding_model_query: str = "text-search-query/latest"
    similarity_threshold: float = 0.72

    # Ollama — сдвоенная стратегия моделей
    llm_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    ollama_model_synth: str = "qwen2.5:14b-instruct-q5_K_M"    # ~10 ГБ VRAM
    ollama_model_tool: str = "qwen2.5:3b-instruct-q5_K_M"      # ~2 ГБ VRAM
    ollama_model_premium: str = "qwen2.5:32b-instruct-q4_K_M"  # ~19 ГБ, опц.
    premium_mode: bool = False
    llm_max_tokens: int = 800
    llm_temperature: float = 0.2
    llm_timeout_s: float = 90.0

    # --- Провайдер LLM: 'ollama' (локально) | 'yandex' (Yandex AI Studio, OpenAI-совм.) ---
    llm_provider: str = "ollama"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_base_url: str = "https://llm.api.cloud.yandex.net/v1"
    # Модели указываются коротко (yandexgpt/latest) или полным URI (gpt://<folder>/<model>).
    # Для open-моделей (deepseek/qwen3/gpt-oss) впиши их URI из консоли AI Studio.
    yandex_model_synth: str = "yandexgpt/latest"
    yandex_model_tool: str = "yandexgpt-lite/latest"

    # Router.AI как fallback (агрегатор российских моделей). Отключено по умолчанию.
    router_ai_enabled: bool = False
    router_ai_url: str = "https://api.router.ai/v1"
    router_ai_api_key: str = ""
    router_ai_model: str = "qwen/qwen-2.5-72b-instruct"

    # Корпус
    corpus_dir: str = "/data/corpus"
    chunk_size: int = 800
    chunk_overlap: int = 200

    # Реальный корпус «Научный клубок»: дерево папок с сырыми документами
    # (Источники информации / Доклады · Журналы · Статьи · Обзоры · Материалы
    # конференций). Обходим рекурсивно; справочники/эксперименты опциональны.
    corpus_recursive: bool = True
    doc_extensions: list[str] = [
        ".pdf", ".docx", ".docm", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt",
    ]
    # Папки, которые не считаем документами при рекурсивном обходе
    corpus_exclude_dirs: list[str] = ["dicts", ".__archive_tmp__"]

    # Вложенные архивы (.zip / .rar / .001-.002) внутри корпуса
    unpack_archives: bool = True
    max_archive_depth: int = 4
    max_uncompressed_mb: int = 30000  # ≥ размер распакованного корпуса (zip ~4.7 ГБ)
    # Конвертация старых бинарных .doc/.ppt/.xls через libreoffice (если доступен)
    soffice_convert: bool = True
    soffice_bin: str = "libreoffice"

    # Извлечение структуры из документов (фаза 2 — опциональный enrichment-проход)
    extract_structured_enabled: bool = False
    extract_max_docs: int = 200
    extract_max_chunks_per_doc: int = 30
    extract_min_confidence: float = 0.55
    useful_info_import_enabled: bool = True
    useful_info_report_path: str = "/outputs/useful_info/useful_info_by_file.jsonl"
    useful_info_enrich_max_tokens: int = 300
    # После IngestService.load_corpus автоматически запускать обогащение
    # useful_info-сниппетов через LLM. Кнопки «Загрузить корпус» и
    # «Обогатить» на UI используют этот же путь.
    useful_info_enrich_on_ingest: bool = True
    # CSV с экспериментами больше не считаем источником истины — их место
    # заняли useful_info-драфты + LLM-экстракция из чанков.
    load_csv_experiments: bool = False
    # Демо-справочник (MAT-001..004, MODE-001..004, PROP-001..004, EQ-001..003,
    # TAG-mech и т.п.) — плейсхолдеры «Материал A1», «Раствор Р1». Настоящие
    # материалы и режимы регистрируются провизорными кодами из LLM-экстракции.
    load_demo_dicts: bool = False
    load_demo_teams: bool = False
    # Модели для двух путей структурной экстракции. Разделены, чтобы можно
    # было запустить фазу 2 (тяжёлые PDF-документы) и обогащение useful_info
    # (короткие сниппеты) параллельно на РАЗНЫХ Ollama-очередях:
    #   - extract  → qwen2.5:3b (быстро прогнать 1600+ документов)
    #   - enrich   → qwen2.5:14b (лучше выделяет материалы/режимы на сниппетах)
    # Обе пустые = fallback на tool-модель (3B). Меняются через env.
    ollama_model_extract: str = ""
    ollama_model_enrich: str = ""

    # CAG-кэш (janson-заимствование): дедуп чанков + кэш ответов Q&A
    chunk_dedup: bool = True
    answer_cache_enabled: bool = True
    answer_cache_ttl_s: int = 604800   # 7 дней
    answer_cache_max: int = 500

    # Full-text seeding ретрива (Neo4j FTS-индексы)
    fts_seed_enabled: bool = True
    fts_seed_limit: int = 15

    # NL→Cypher как опциональный fallback (по умолчанию выключен из соображений ИБ)
    nl2cypher_enabled: bool = False
    nl2cypher_row_limit: int = 50

    # Поведение
    log_level: str = "INFO"
    graph_max_nodes: int = 500
    request_timeout_s: float = 30.0

    # Auto-enrichment
    auto_enrichment_enabled: bool = True
    auto_enrichment_batch_interval_s: int = 300  # раз в 5 минут — тяжёлые шаги
    contradiction_confidence_threshold: float = 0.75

    # Автоингест при старте: если Neo4j пустой (нет ни одного Document/Experiment),
    # запустим IngestService().load_corpus() в фоновом потоке. Это даёт «датасет из
    # коробки»: развернул compose — и всё уже в БД. Флаг можно выключить через env.
    auto_ingest_on_startup: bool = True

    # Параллельный парсинг документов: 0 = последовательно (старое поведение),
    # >=2 = ProcessPoolExecutor с N воркерами. На 8-ядерном CPU оптимум ~6-7.
    ingest_workers: int = 6

    # Температурные бакеты для матрицы пробелов (без металлургической специфики)
    temp_buckets: list[int] = [0, 200, 400, 600, 800, 1000, 1200, 1500]


settings = Settings()


def synth_model():
    """Возвращает имя модели для синтеза с учётом premium_mode."""
    return settings.ollama_model_premium if settings.premium_mode else settings.ollama_model_synth

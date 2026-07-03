"""Тесты CAG-кэша, дедупа чанков и валидатора NL→Cypher (read-only).

Проверяют чистую логику без Neo4j/Qdrant/Ollama.
"""

import time

import pytest

from app.services import cache_service
from app.services.cache_service import AnswerCache
from app.services.nl2cypher_service import _is_read_only, _ensure_limit
from app.services.graph_service import _lucene_escape


# --------------------------------------------------------------------------
# Дедуп чанков
# --------------------------------------------------------------------------

def test_chunk_point_id_is_deterministic_and_normalized():
    a = cache_service.chunk_point_id("Флотация  меди\n при pH 9")
    b = cache_service.chunk_point_id("флотация меди при ph 9")  # регистр/пробелы
    c = cache_service.chunk_point_id("совсем другой чанк")
    assert a == b            # нормализация → один и тот же id
    assert a != c
    # валидный UUID-формат
    import uuid
    uuid.UUID(a)


def test_chunk_content_hash_matches_id_source():
    h1 = cache_service.chunk_content_hash("Текст  A")
    h2 = cache_service.chunk_content_hash("текст a")
    assert h1 == h2 and len(h1) == 64


# --------------------------------------------------------------------------
# AnswerCache: TTL + LRU
# --------------------------------------------------------------------------

def test_answer_cache_hit_and_key_sensitivity():
    c = AnswerCache(ttl_s=100, max_size=10)
    c.set("Какие методы обессоливания?", {"answer": "ok"}, geo_filter="domestic")
    assert c.get("какие  методы обессоливания?", geo_filter="domestic")["answer"] == "ok"
    # другой geo → промах
    assert c.get("Какие методы обессоливания?", geo_filter="foreign") is None


def test_answer_cache_ttl_expiry():
    c = AnswerCache(ttl_s=0, max_size=10)  # мгновенно протухает
    c.set("q", {"answer": "x"})
    time.sleep(0.01)
    assert c.get("q") is None


def test_answer_cache_lru_eviction():
    c = AnswerCache(ttl_s=1000, max_size=2)
    c.set("q1", {"a": 1}); c.set("q2", {"a": 2})
    c.get("q1")                 # q1 становится свежим
    c.set("q3", {"a": 3})       # вытеснит q2 (самый старый по использованию)
    assert c.get("q1") is not None
    assert c.get("q2") is None
    assert c.get("q3") is not None


# --------------------------------------------------------------------------
# NL→Cypher: read-only guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cypher", [
    "MATCH (e:Experiment) RETURN e.title LIMIT 10",
    "  match (m:Material) where m.display_name contains 'никель' return m limit 5",
    "CALL db.index.fulltext.queryNodes('document_search','медь') YIELD node RETURN node LIMIT 5",
    "WITH 1 AS x RETURN x",
])
def test_read_only_accepts_reads(cypher):
    assert _is_read_only(cypher) is True


@pytest.mark.parametrize("cypher", [
    "MATCH (e) DETACH DELETE e",
    "CREATE (x:Material {code:'X'}) RETURN x",
    "MATCH (m:Material) SET m.hacked = true RETURN m",
    "MERGE (a:Author {author_id:'Z'})",
    "MATCH (n) REMOVE n.prop RETURN n",
    "CALL apoc.periodic.iterate('MATCH (n) RETURN n','DELETE n',{})",
    "DROP INDEX foo",
    "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
    "",
])
def test_read_only_rejects_writes(cypher):
    assert _is_read_only(cypher) is False


def test_ensure_limit_appends_when_missing():
    assert "LIMIT 50" in _ensure_limit("MATCH (n) RETURN n", 50)
    # уже есть LIMIT — не дублируем
    out = _ensure_limit("MATCH (n) RETURN n LIMIT 5", 50)
    assert out.count("LIMIT") == 1


# --------------------------------------------------------------------------
# Lucene-экранирование для FTS
# --------------------------------------------------------------------------

def test_lucene_escape_builds_or_query_and_escapes():
    q = _lucene_escape("никель (электроэкстракция) pH:9")
    assert " OR " in q
    assert "никель" in q
    # спецсимволы экранированы (нет «голых» ( ) :)
    assert "(" not in q.replace("\\(", "")


# --------------------------------------------------------------------------
# Yandex-провайдер: построение URI модели + мягкий парсинг JSON
# --------------------------------------------------------------------------

from app.services.llm_service import yandex_model_uri, _parse_json_loose  # noqa: E402


def test_yandex_model_uri_short_and_full():
    short = yandex_model_uri("yandexgpt/latest")
    assert short.startswith("gpt://") and short.endswith("/yandexgpt/latest")
    full = "gpt://b1ggusvist6c2sia1dno/deepseek-v3/latest"
    assert yandex_model_uri(full) == full           # полный URI не трогаем


def test_parse_json_loose():
    assert _parse_json_loose('{"a": 1}') == {"a": 1}
    assert _parse_json_loose('текст перед {"a": 2} и после') == {"a": 2}
    assert _parse_json_loose("не json") is None
    assert _parse_json_loose("") is None

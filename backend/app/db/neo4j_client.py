"""Neo4j клиент + схема (11 типов узлов, доменные индексы)."""

from neo4j import GraphDatabase
from loguru import logger

from app.config import settings


class Neo4jClient:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def apply_schema(self):
        stmts = [
            # Уникальность
            "CREATE CONSTRAINT material_code IF NOT EXISTS FOR (m:Material) REQUIRE m.code IS UNIQUE",
            "CREATE CONSTRAINT property_code IF NOT EXISTS FOR (p:Property) REQUIRE p.code IS UNIQUE",
            "CREATE CONSTRAINT mode_code IF NOT EXISTS FOR (mo:Mode) REQUIRE mo.code IS UNIQUE",
            "CREATE CONSTRAINT equipment_code IF NOT EXISTS FOR (eq:Equipment) REQUIRE eq.code IS UNIQUE",
            "CREATE CONSTRAINT experiment_id IF NOT EXISTS FOR (e:Experiment) REQUIRE e.experiment_id IS UNIQUE",
            "CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.author_id IS UNIQUE",
            "CREATE CONSTRAINT team_id IF NOT EXISTS FOR (t:Team) REQUIRE t.team_id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT tag_code IF NOT EXISTS FOR (tg:Tag) REQUIRE tg.code IS UNIQUE",
            "CREATE CONSTRAINT conclusion_id IF NOT EXISTS FOR (c:Conclusion) REQUIRE c.conclusion_id IS UNIQUE",
            # Fulltext
            "CREATE FULLTEXT INDEX material_search IF NOT EXISTS FOR (m:Material) ON EACH [m.display_name, m.aliases]",
            "CREATE FULLTEXT INDEX property_search IF NOT EXISTS FOR (p:Property) ON EACH [p.display_name, p.aliases]",
            "CREATE FULLTEXT INDEX mode_search IF NOT EXISTS FOR (mo:Mode) ON EACH [mo.display_name]",
            "CREATE FULLTEXT INDEX experiment_search IF NOT EXISTS FOR (e:Experiment) ON EACH [e.title, e.description]",
            "CREATE FULLTEXT INDEX document_search IF NOT EXISTS FOR (d:Document) ON EACH [d.title, d.summary]",
            # Обычные — под фильтры
            "CREATE INDEX experiment_year IF NOT EXISTS FOR (e:Experiment) ON (e.year)",
            "CREATE INDEX mode_temp IF NOT EXISTS FOR (mo:Mode) ON (mo.temperature_c)",
            "CREATE INDEX document_country IF NOT EXISTS FOR (d:Document) ON (d.country_code)",
            "CREATE INDEX document_region IF NOT EXISTS FOR (d:Document) ON (d.geo_region)",
            "CREATE INDEX document_language IF NOT EXISTS FOR (d:Document) ON (d.language)",
            # Верификация фактов
            "CREATE INDEX conclusion_confidence IF NOT EXISTS FOR (c:Conclusion) ON (c.confidence)",
            "CREATE INDEX conclusion_updated IF NOT EXISTS FOR (c:Conclusion) ON (c.last_updated)",
            # ModeParam — расширенные диапазоны
            "CREATE INDEX modeparam_name IF NOT EXISTS FOR (p:ModeParam) ON (p.name)",
            "CREATE INDEX modeparam_value IF NOT EXISTS FOR (p:ModeParam) ON (p.value)",
            # source Experiment — ускоряет DocExtractionService._list_useful_info_experiments
            # (SELECT WHERE e.source='useful_info' на 10k+ узлах)
            "CREATE INDEX experiment_source IF NOT EXISTS FOR (e:Experiment) ON (e.source)",
            # Индекс по значению MEASURED — ускоряет фильтры «r.value IS NOT NULL»
            # (без индекса это скан всех MEASURED-рёбер, а их десятки тысяч).
            "CREATE INDEX measured_value IF NOT EXISTS FOR ()-[r:MEASURED]-() ON (r.value)",
        ]
        with self.driver.session() as s:
            for q in stmts:
                try:
                    s.run(q)
                except Exception as e:
                    logger.warning(f"schema stmt failed (ok if exists): {e}")


_client = None


def init_neo4j():
    global _client
    _client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    logger.info(f"Neo4j connected: {settings.neo4j_uri}")


def get_neo4j():
    if _client is None:
        raise RuntimeError("Neo4j not initialized")
    return _client


def close_neo4j():
    global _client
    if _client:
        _client.close()
        _client = None

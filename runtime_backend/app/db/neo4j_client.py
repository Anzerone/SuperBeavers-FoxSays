from contextlib import suppress

from loguru import logger
from neo4j import GraphDatabase

from app.config import get_settings
from app.models import Experiment


class Neo4jGraphStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.driver = None
        if self.settings.neo4j_enabled:
            self.driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )

    def close(self) -> None:
        if self.driver:
            self.driver.close()

    def ensure_schema(self) -> None:
        if not self.driver:
            return
        statements = [
            "CREATE CONSTRAINT experiment_id IF NOT EXISTS FOR (e:Experiment) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT material_name IF NOT EXISTS FOR (m:Material) REQUIRE m.name IS UNIQUE",
            "CREATE CONSTRAINT process_name IF NOT EXISTS FOR (p:Process) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT property_name IF NOT EXISTS FOR (p:Property) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT document_title IF NOT EXISTS FOR (d:Document) REQUIRE d.title IS UNIQUE",
        ]
        with self.driver.session() as session:
            for statement in statements:
                session.run(statement)

    def upsert_experiments(self, experiments: list[Experiment]) -> None:
        if not self.driver or not experiments:
            return
        self.ensure_schema()
        with self.driver.session() as session:
            for item in experiments:
                session.execute_write(self._upsert_one, item.model_dump())
        logger.info("Upserted {} experiments to Neo4j", len(experiments))

    @staticmethod
    def _upsert_one(tx, item: dict) -> None:
        tx.run(
            """
            MERGE (e:Experiment {id: $id})
            SET e.title = $title,
                e.condition = $condition,
                e.result = $result,
                e.value = $value,
                e.geography = $geography,
                e.year = $year,
                e.confidence = $confidence
            MERGE (m:Material {name: $material})
            MERGE (p:Process {name: $process})
            MERGE (prop:Property {name: $property})
            MERGE (d:Document {title: $source})
            MERGE (e)-[:USED_MATERIAL]->(m)
            MERGE (e)-[:USED_PROCESS]->(p)
            MERGE (e)-[:MEASURED]->(prop)
            MERGE (e)-[:DOCUMENTED_IN]->(d)
            """,
            **item,
        )


with suppress(Exception):
    graph_store = Neo4jGraphStore()


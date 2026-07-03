"""Промпт NL→Cypher (заимствование у TasFoster) — генерация READ-ONLY Cypher.

LLM получает схему онтологии и вопрос, возвращает единственный запрос чтения.
Любой сгенерированный запрос дополнительно валидируется на read-only ПЕРЕД
выполнением (см. nl2cypher_service._is_read_only).
"""

SYSTEM = (
    "Ты переводишь вопрос пользователя в ОДИН read-only Cypher-запрос к Neo4j. "
    "Только чтение: запрещены CREATE, MERGE, DELETE, SET, REMOVE, DROP, LOAD CSV, "
    "процедуры записи. Всегда добавляй LIMIT. Ответ — строго JSON {\"cypher\": \"...\"}."
)

SCHEMA = """Онтология (узлы : ключ [свойства]):
  Material:code [display_name, family]
  Property:code [display_name, unit]
  Mode:code [display_name, temperature_c, duration_h]
  ModeParam [name, value, unit]              # name ∈ temperature|concentration|flow_rate|pressure|ph|current_density|cost|throughput
  Equipment:code [display_name]
  Experiment:experiment_id [title, year, description]
  Conclusion:conclusion_id [text, confidence, last_updated]
  Document:doc_id [title, doc_type, journal, year, geo_region, country_code]
  Author:author_id [full_name]; Team:team_id; Tag:code

Рёбра:
  (Experiment)-[:USED_MATERIAL]->(Material)
  (Experiment)-[:USED_MODE]->(Mode)-[:HAS_PARAM]->(ModeParam)
  (Experiment)-[:USED_EQUIPMENT]->(Equipment)
  (Experiment)-[:MEASURED {value,unit}]->(Property)
  (Experiment)-[:RESULTED_IN]->(Conclusion)
  (Experiment)-[:DOCUMENTED_IN]->(Document)
  (Experiment)-[:CONDUCTED_BY]->(Author)-[:MEMBER_OF]->(Team)
  (Experiment)-[:SIMILAR_TO]->(Experiment)
  (Conclusion)-[:CONFIRMS|CONTRADICTS|SUPERSEDED_BY]->(Conclusion)
  (Document)-[:MENTIONS]->(Material|Mode|Property)

geo_region ∈ 'domestic' (РФ/СНГ) | 'foreign' | 'other'."""


def build_prompt(question, row_limit=50):
    return (
        f"{SCHEMA}\n\n"
        f"Вопрос: «{question}»\n\n"
        f"Верни JSON с одним read-only Cypher (обязательно LIMIT {row_limit}). "
        f"Пример: {{\"cypher\": \"MATCH (e:Experiment)-[:USED_MATERIAL]->(m:Material) "
        f"WHERE m.display_name CONTAINS 'никель' RETURN e.title, e.year LIMIT {row_limit}\"}}"
    )

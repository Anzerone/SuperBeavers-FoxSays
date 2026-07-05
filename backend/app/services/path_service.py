"""PathService: путь между двумя сущностями через APOC Dijkstra.

Используется для сценария «история эксперимента» — найти, как один материал/
эксперимент/автор связан с другим через цепочку рёбер.
"""

from __future__ import annotations

from loguru import logger

from app.db.neo4j_client import get_neo4j

# Все типы рёбер, по которым ходим (undirected)
REL_TYPES = (
    "USED_MATERIAL|USED_MODE|USED_EQUIPMENT|MEASURED|HAS_PARAM|"
    "RESULTED_IN|CONDUCTED_BY|MEMBER_OF|DOCUMENTED_IN|MENTIONS|"
    "CITES|SIMILAR_TO|TAGGED_WITH|RELATED_TO|CONFIRMS|CONTRADICTS"
)


class PathService:

    def find_path(self, src_label, src_code, dst_label, dst_code):
        """Кратчайший взвешенный путь между двумя любыми сущностями."""
        neo = get_neo4j()
        with neo.driver.session() as s:
            try:
                return s.execute_read(
                    _tx_path_apoc,
                    src_label, src_code, dst_label, dst_code,
                )
            except Exception as e:
                logger.warning(f"APOC dijkstra failed: {e}; fallback")
                return s.execute_read(
                    _tx_path_fallback,
                    src_label, src_code, dst_label, dst_code,
                )


def _key_field(label):
    return {
        "Material": "code", "Property": "code", "Mode": "code",
        "Equipment": "code", "Tag": "code",
        "Experiment": "experiment_id", "Author": "author_id",
        "Team": "team_id", "Document": "doc_id",
        "Conclusion": "conclusion_id",
    }.get(label)


def _tx_path_apoc(tx, src_label, src_code, dst_label, dst_code):
    src_key = _key_field(src_label)
    dst_key = _key_field(dst_label)
    if not src_key or not dst_key:
        return None
    q = f"""
    MATCH (a:{src_label} {{{src_key}: $src}}), (b:{dst_label} {{{dst_key}: $dst}})
    CALL apoc.algo.dijkstra(a, b, '{REL_TYPES}', 'weight')
    YIELD path, weight
    RETURN [n IN nodes(path) | {{
              id: coalesce(n.experiment_id, n.code, n.author_id, n.team_id,
                           n.doc_id, n.conclusion_id),
              labels: labels(n),
              title: coalesce(n.display_name, n.title, n.full_name, n.text)
           }}] AS nodes,
           [r IN relationships(path) | {{type: type(r), weight: r.weight}}] AS edges,
           weight
    LIMIT 1
    """
    rec = tx.run(q, src=src_code, dst=dst_code).single()
    if not rec:
        return None
    return {
        "nodes": rec["nodes"],
        "edges": rec["edges"],
        "weight": float(rec["weight"]),
    }


def _tx_path_fallback(tx, src_label, src_code, dst_label, dst_code):
    src_key = _key_field(src_label)
    dst_key = _key_field(dst_label)
    if not src_key or not dst_key:
        return None
    q = f"""
    MATCH (a:{src_label} {{{src_key}: $src}}), (b:{dst_label} {{{dst_key}: $dst}}),
          p = shortestPath((a)-[*..8]-(b))
    RETURN [n IN nodes(p) | {{
              id: coalesce(n.experiment_id, n.code, n.author_id, n.team_id,
                           n.doc_id, n.conclusion_id),
              labels: labels(n),
              title: coalesce(n.display_name, n.title, n.full_name, n.text)
           }}] AS nodes,
           [r IN relationships(p) | {{type: type(r), weight: r.weight}}] AS edges,
           length(p) AS len
    LIMIT 1
    """
    rec = tx.run(q, src=src_code, dst=dst_code).single()
    if not rec:
        return None
    return {
        "nodes": rec["nodes"],
        "edges": rec["edges"],
        "weight": float(rec["len"]),
    }

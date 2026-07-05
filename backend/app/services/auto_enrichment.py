"""AutoEnrichmentService: самообогащающийся граф.

При добавлении новой сущности (Document / Experiment / Material / ...) запускает
цепочку шагов, каждый следующий дороже:
  1. Semantic similarity (Qdrant поиск похожих)          — быстро
  2. NER из документа → :MENTIONS                        — Qwen 3B, средне
  3. Cypher-правила (индукция по паттернам)              — быстро
  4. Structural link prediction (GDS Adamic-Adar)        — средне
  5. Conclusion-сравнение → :CONFIRMS/:CONTRADICTS       — Qwen 7B, дорого
  6. Community detection (Louvain) + PageRank            — GDS, средне

Спорные связи (confidence < 0.75) уходят в очередь human-review, не пишутся сразу.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger

from app.config import settings
from app.db.neo4j_client import get_neo4j
from app.services import dictionary
from app.services.llm_service import LLMService
from app.services.ner_service import NERService
from app.services.rag_service import RAGService


class AutoEnrichmentService:
    """Список событий обогащения — для стрима на UI через WebSocket."""

    def __init__(self, llm: LLMService, rag: RAGService, ner: NERService):
        self.llm = llm
        self.rag = rag
        self.ner = ner
        self.events: list[dict[str, Any]] = []

    def _emit(self, event_type, payload):
        ev = {"type": event_type, **payload}
        self.events.append(ev)
        logger.info(f"[enrich] {event_type}: {payload}")

    async def enrich_document(self, doc_id, chunks):
        """После ingest'а нового документа: NER на каждом чанке + связи."""
        # шаг 1: NER пакетно, батч по 5 чанков
        ner_results = defaultdict(set)  # entity_type -> {(raw, match)}
        for chunk in chunks[:20]:  # экономия: первые 20 чанков документа
            r = await self.ner.extract(chunk["text"])
            for kind in ("materials", "modes", "properties"):
                for it in r[kind]:
                    if it.get("match"):
                        ner_results[kind].add(it["match"])

        neo = get_neo4j()
        added = 0
        with neo.driver.session() as s:
            for kind, labels in (
                ("materials", "Material"), ("modes", "Mode"), ("properties", "Property"),
            ):
                for code in ner_results[kind]:
                    s.execute_write(_tx_link_mention, doc_id, labels, code, 0.9)
                    added += 1
        self._emit("mentions_added", {"doc_id": doc_id, "count": added})

    async def enrich_experiment(self, experiment_id):
        """После ingest'а эксперимента: semantic SIMILAR_TO + cypher-правила."""
        neo = get_neo4j()
        # 1. Semantic similarity к другим экспериментам
        similar = self.rag.search_similar_experiments(
            self._get_experiment_desc(experiment_id), top_k=8
        )
        added_sim = 0
        with neo.driver.session() as s:
            for r in similar:
                if r["experiment_id"] == experiment_id:
                    continue
                weight = max(0.5, 1.5 / max(r["score"], 0.01))
                s.execute_write(
                    _tx_link_similar, experiment_id, r["experiment_id"],
                    r["score"], weight, "text",
                )
                added_sim += 1
        self._emit("similar_added", {"experiment_id": experiment_id, "count": added_sim})

        # 2. Cypher-правило: эксперименты с общим Material+Mode
        with neo.driver.session() as s:
            rule_added = s.execute_write(_tx_rule_common_material_mode, experiment_id)
        self._emit("rule_similar_added", {"experiment_id": experiment_id, "count": rule_added})

    async def compare_conclusions(self, conclusion_id):
        """LLM-сравнение нового вывода с топ-5 похожими → :CONFIRMS / :CONTRADICTS."""
        neo = get_neo4j()
        with neo.driver.session() as s:
            rec = s.run(
                "MATCH (c:Conclusion {conclusion_id: $id}) RETURN c.text AS text",
                id=conclusion_id,
            ).single()
        if not rec:
            return
        new_text = rec["text"]

        # Ищем похожие Conclusion через эмбеддинги
        [vec] = self.rag.embed_texts([new_text])
        # для Conclusion своей коллекции нет — используем общую логику эмбеддинга на лету
        with neo.driver.session() as s:
            candidates = list(s.run(
                "MATCH (c:Conclusion) WHERE c.conclusion_id <> $id "
                "RETURN c.conclusion_id AS id, c.text AS text LIMIT 20",
                id=conclusion_id,
            ))
        if not candidates:
            return

        cand_texts = [c["text"] or "" for c in candidates]
        cand_vecs = self.rag.embed_texts(cand_texts)
        # rank by cosine (dot, since we use normalized BGE-M3 → уже нормализованы Qdrant'ом,
        # но fastembed возвращает ненормализованные; правильнее делать в Qdrant)
        # Упрощённо: топ-3 по косинусной близости эмбеддингов
        import math
        def _cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb + 1e-9)
        scored = sorted(
            zip(candidates, cand_vecs),
            key=lambda p: _cos(vec, p[1]), reverse=True
        )[:3]

        prompt_prefix = (
            "Сравни два вывода и определи отношение. Ответ строго JSON: "
            '{"relation": "confirms"|"contradicts"|"unrelated", "confidence": 0.0-1.0, "reason": "..."}\n\n'
        )
        for cand, _v in scored:
            prompt = prompt_prefix + f"ВЫВОД A: «{new_text[:600]}»\n\nВЫВОД B: «{cand['text'][:600]}»\n\nJSON:"
            r = await self.llm.generate_json(
                prompt,
                system="Ты — эксперт, сравнивающий научные выводы. Отвечай строго JSON.",
                model=settings.ollama_model_synth, max_tokens=200,
            )
            if not r:
                continue
            rel = (r.get("relation") or "").lower()
            conf = float(r.get("confidence") or 0.0)
            if rel in ("confirms", "contradicts") and conf >= 0.75:
                edge_type = "CONFIRMS" if rel == "confirms" else "CONTRADICTS"
                with neo.driver.session() as s:
                    s.execute_write(_tx_link_conclusion, conclusion_id, cand["id"], edge_type, conf)
                self._emit("conclusion_relation", {
                    "src": conclusion_id, "dst": cand["id"], "type": edge_type, "confidence": conf,
                })
            elif rel in ("confirms", "contradicts"):
                # спорные — в очередь human-review
                self._emit("review_pending", {
                    "src": conclusion_id, "dst": cand["id"],
                    "proposed_type": rel.upper(), "confidence": conf,
                    "reason": r.get("reason", "")[:200],
                })

    def refresh_pagerank_and_communities(self, min_new_percent=5):
        """GDS PageRank + Louvain, если добавлено >min_new_percent узлов."""
        neo = get_neo4j()
        with neo.driver.session() as s:
            # PageRank inline (без проекций для простоты)
            try:
                s.run("""
                CALL gds.graph.project('enrich', ['Experiment','Material','Property','Mode','Author','Document'],
                    {ALL: {type: '*', orientation: 'UNDIRECTED'}})
                YIELD graphName
                """)
                s.run("""
                CALL gds.pageRank.write('enrich', {writeProperty: 'pagerank'})
                YIELD nodePropertiesWritten
                """)
                s.run("""
                CALL gds.louvain.write('enrich', {writeProperty: 'community'})
                YIELD nodePropertiesWritten
                """)
                s.run("CALL gds.graph.drop('enrich') YIELD graphName")
                self._emit("pagerank_louvain_done", {})
            except Exception as e:
                logger.warning(f"GDS PageRank/Louvain failed: {e}")

    def link_predictor(self, sample=100):
        """GDS Adamic-Adar link prediction по topology — возвращает топ-N пар
        Experiment↔Experiment без прямой связи, но с высокой topology-схожестью."""
        neo = get_neo4j()
        try:
            with neo.driver.session() as s:
                res = list(s.run("""
                MATCH (a:Experiment), (b:Experiment)
                WHERE elementId(a) < elementId(b) AND NOT (a)-[:SIMILAR_TO]-(b)
                WITH a, b, gds.alpha.linkprediction.adamicAdar(a, b) AS score
                WHERE score > 0.1
                RETURN a.experiment_id AS a_id, b.experiment_id AS b_id, score
                ORDER BY score DESC LIMIT $lim
                """, lim=sample))
            self._emit("link_prediction_done", {"count": len(res)})
            return [{"a": r["a_id"], "b": r["b_id"], "score": r["score"]} for r in res]
        except Exception as e:
            logger.warning(f"Link prediction failed: {e}")
            return []

    def _get_experiment_desc(self, experiment_id):
        neo = get_neo4j()
        with neo.driver.session() as s:
            r = s.run(
                "MATCH (e:Experiment {experiment_id: $id}) "
                "RETURN e.title + ' ' + coalesce(e.description, '') AS d",
                id=experiment_id,
            ).single()
        return r["d"] if r else ""


# ---------- Cypher транзакции ----------


def _tx_link_mention(tx, doc_id, target_label, target_code, confidence):
    tx.run(
        f"""
        MATCH (d:Document {{doc_id: $did}}), (t:{target_label} {{code: $code}})
        MERGE (d)-[r:MENTIONS]->(t)
        SET r.confidence = $conf
        """,
        did=doc_id, code=target_code, conf=confidence,
    )


def _tx_link_similar(tx, a_id, b_id, score, weight, source):
    tx.run(
        """
        MATCH (a:Experiment {experiment_id: $a}), (b:Experiment {experiment_id: $b})
        WHERE elementId(a) < elementId(b)
        MERGE (a)-[r:SIMILAR_TO]->(b)
        SET r.score = coalesce(r.score, 0),
            r.score = CASE WHEN $score > r.score THEN $score ELSE r.score END,
            r.weight = $weight,
            r.source = $source
        """,
        a=a_id, b=b_id, score=score, weight=weight, source=source,
    )


def _tx_rule_common_material_mode(tx, exp_id):
    """Правило: два эксперимента с общим Material И общим Mode →
    :SIMILAR_TO с source='rule'."""
    result = tx.run("""
        MATCH (e:Experiment {experiment_id: $id})-[:USED_MATERIAL]->(m:Material)
              <-[:USED_MATERIAL]-(e2:Experiment)
        MATCH (e)-[:USED_MODE]->(mo:Mode)<-[:USED_MODE]-(e2)
        WHERE elementId(e) < elementId(e2)
        MERGE (e)-[r:SIMILAR_TO]->(e2)
        SET r.score = coalesce(r.score, 0.6),
            r.weight = coalesce(r.weight, 0.8),
            r.source = coalesce(r.source, 'rule')
        RETURN count(e2) AS added
    """, id=exp_id)
    rec = result.single()
    return rec["added"] if rec else 0


def _tx_link_conclusion(tx, src, dst, edge_type, confidence):
    tx.run(
        f"""
        MATCH (a:Conclusion {{conclusion_id: $src}}),
              (b:Conclusion {{conclusion_id: $dst}})
        MERGE (a)-[r:{edge_type}]->(b)
        SET r.confidence = $conf
        """,
        src=src, dst=dst, conf=confidence,
    )

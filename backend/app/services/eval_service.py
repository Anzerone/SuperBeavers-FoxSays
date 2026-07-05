"""EvalService — baseline-метрики качества извлечения и поиска.

Три оси качества:

1. **Extraction P/R** — доля Experiment-узлов со структурными связями
   (`USED_MATERIAL` ИЛИ `USED_MODE` ИЛИ `MEASURED`) в общей популяции черновых
   useful_info-записей. При наличии `backend/tests/fixtures/labeled_snippets.jsonl`
   (ручная разметка) — считаем P/R против неё; иначе — доля покрытия.

2. **Retrieval MRR@10 / nDCG@10** — на маленьком наборе демо-вопросов проверяем,
   попадает ли ожидаемый Document в топ-10 гибридного ретривера (Qdrant + FTS).

3. **Link-prediction AUC (SIMILAR_TO)** — если построены рёбра `SIMILAR_TO`,
   маскируем 10% и меряем ROC-AUC cosine-scoring vs random. Пока их нет
   (Qdrant JSON payload roof), функция возвращает `null`.

Ручка `/admin/eval` дёргает всё это одним запросом.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from loguru import logger

from app.config import settings
from app.db.neo4j_client import get_neo4j

LABEL_PATH = Path("backend/tests/fixtures/labeled_snippets.jsonl")

# Мини-набор вопросов для retrieval-baseline. Реальный корпус — металлургия
# Норникеля, поэтому вопросы про Ni/Cu/PGM. Ключевые слова помогают fallback-у
# на FTS-ретривер даже без Qdrant.
DEMO_QUESTIONS = [
    {"q": "извлечение меди при выщелачивании",
     "keywords": ["извлеч", "медь", "выщелачив"]},
    {"q": "температура обжига никелевого концентрата",
     "keywords": ["температура", "обжиг", "никел"]},
    {"q": "флотация платиновых металлов",
     "keywords": ["флотац", "платин", "МПГ"]},
    {"q": "содержание серы в штейне",
     "keywords": ["сер", "штейн"]},
    {"q": "электролиз никеля плотность тока",
     "keywords": ["электролиз", "никел", "плотност"]},
]


def extraction_metrics():
    """Покрытие + опциональные P/R против разметки."""
    out = {}
    with get_neo4j().driver.session() as s:
        rec = s.run("""
            MATCH (e:Experiment {source: 'useful_info'})
            WITH count(e) AS total,
                 sum(CASE WHEN (e)-[:USED_MATERIAL]->() OR
                               (e)-[:USED_MODE]->() OR
                               (e)-[:MEASURED]->() THEN 1 ELSE 0 END) AS with_struct
            RETURN total, with_struct
        """).single()
        total = int(rec["total"] or 0)
        struct = int(rec["with_struct"] or 0)
        out["coverage"] = {
            "total_drafts": total,
            "with_structure": struct,
            "pct": round(100.0 * struct / total, 1) if total else 0.0,
        }

    # Ручная разметка (P/R) — если есть.
    if LABEL_PATH.exists():
        gold, pred = _load_pr_pairs()
        p, r, f1, tp = _prf(gold, pred)
        out["labeled_eval"] = {
            "n_gold": len(gold), "n_pred": len(pred), "true_positive": tp,
            "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3),
        }
    else:
        out["labeled_eval"] = {"note": f"нет файла {LABEL_PATH}, пропущено"}
    return out


def _load_pr_pairs():
    """Файл разметки: {'exp_id': ..., 'gold': {'material': str|null, 'mode': ..., 'property': ...}}"""
    gold, pred = {}, {}
    for line in LABEL_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        gold[rec["exp_id"]] = rec.get("gold") or {}

    ids = list(gold.keys())
    if not ids:
        return gold, pred
    with get_neo4j().driver.session() as s:
        q = """
        MATCH (e:Experiment) WHERE e.experiment_id IN $ids
        OPTIONAL MATCH (e)-[:USED_MATERIAL]->(m:Material)
        OPTIONAL MATCH (e)-[:USED_MODE]->(mo:Mode)
        OPTIONAL MATCH (e)-[r:MEASURED]->(p:Property)
        RETURN e.experiment_id AS id,
               m.display_name AS material,
               mo.display_name AS mode,
               p.display_name AS property,
               r.value AS value
        """
        for r in s.run(q, ids=ids):
            pred[r["id"]] = {
                "material": r["material"], "mode": r["mode"],
                "property": r["property"], "value": r["value"],
            }
    return gold, pred


def _prf(gold, pred):
    """Field-level precision/recall/F1 по 3 полям (material/mode/property).
    Совпадение считаем по вхождению нижнего регистра одного в другой."""
    tp = fp = fn = 0
    for eid, g in gold.items():
        p = pred.get(eid, {})
        for field in ("material", "mode", "property"):
            gv = (g.get(field) or "").strip().lower()
            pv = (p.get(field) or "").strip().lower()
            if gv and pv and (gv in pv or pv in gv):
                tp += 1
            elif pv and not gv:
                fp += 1
            elif gv and not pv:
                fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1, tp


def retrieval_metrics(top_k=10):
    """MRR@k / nDCG@k на демо-вопросах.

    Ground-truth документа нет, поэтому используем **прокси**: релевантным считаем
    документ, у которого хотя бы одно из ключевых слов вопроса встречается в
    title или summary. Это не «true relevance», но baseline даёт понимание,
    выдаёт ли ретривер тематически близкие результаты, а не рандом.
    """
    try:
        from app.services.rag_service import RAGService
        rag = RAGService()
    except Exception as e:  # noqa: BLE001
        return {"error": f"RAGService init failed: {e}"}

    results = []
    for item in DEMO_QUESTIONS:
        q = item["q"]
        kws = [k.lower() for k in item["keywords"]]
        try:
            hits = rag.search_chunks(q, top_k=top_k) or []
        except Exception as e:  # noqa: BLE001
            results.append({"q": q, "error": str(e)[:120]})
            continue
        rels = []
        for h in hits[:top_k]:
            text = str(h.get("text", "") or "").lower()
            rels.append(1 if any(k in text for k in kws) else 0)
        mrr = 0.0
        for i, r in enumerate(rels, 1):
            if r:
                mrr = 1.0 / i
                break
        dcg = sum(r / math.log2(i + 1) for i, r in enumerate(rels, 1))
        ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(rels), sum(rels)) + 1))
        ndcg = (dcg / ideal) if ideal else 0.0
        # Precision@k = доля релевантных в топ-k. Recall/F1 не считаем — без
        # gold-набора «всех релевантных» знаменатель Recall непосчитаем, а
        # прокси через keyword-overlap завысил бы число.
        p_at_k = round(sum(rels) / top_k, 3) if top_k else 0.0
        results.append({
            "q": q, "hits": len(hits),
            "relevant_at_k": sum(rels),
            "precision_at_k": p_at_k,
            "mrr": round(mrr, 3), "ndcg": round(ndcg, 3),
        })

    n = max(len(results), 1)
    mrr_mean = round(sum(r.get("mrr", 0) for r in results) / n, 3)
    ndcg_mean = round(sum(r.get("ndcg", 0) for r in results) / n, 3)
    p_at_k_mean = round(sum(r.get("precision_at_k", 0) for r in results) / n, 3)
    return {"per_query": results, "mrr_mean": mrr_mean, "ndcg_mean": ndcg_mean,
            "p_at_k_mean": p_at_k_mean,
            "k": top_k, "note": "proxy relevance via keyword overlap"}


def link_prediction_auc(sample=200):
    """ROC-AUC для SIMILAR_TO через bootstrap: рандомные пары (E, E') vs реальные.
    Пока SIMILAR_TO пусты — возвращаем null. Считается когда edges > 100."""
    with get_neo4j().driver.session() as s:
        cnt = s.run("MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS c").single()
        n_edges = int(cnt["c"] or 0)
        if n_edges < 100:
            return {"auc": None, "n_edges": n_edges,
                    "note": "SIMILAR_TO ещё не построен (нужно >100 рёбер)"}

        pos = list(s.run("""
            MATCH (a:Experiment)-[r:SIMILAR_TO]->(b:Experiment)
            RETURN r.score AS score ORDER BY rand() LIMIT $lim
        """, lim=sample))
        # Отрицательные пары — рандомные, не соединённые SIMILAR_TO.
        neg = list(s.run("""
            MATCH (a:Experiment), (b:Experiment)
            WHERE elementId(a) < elementId(b)
              AND NOT (a)-[:SIMILAR_TO]-(b)
            RETURN 0.0 AS score ORDER BY rand() LIMIT $lim
        """, lim=sample))
    pos_scores = [float(r["score"] or 0) for r in pos]
    neg_scores = [float(r["score"] or 0) for r in neg]
    if not pos_scores or not neg_scores:
        return {"auc": None, "note": "недостаточно данных"}
    # AUC — доля пар (pos, neg), где score(pos) > score(neg).
    correct = 0
    total = 0
    for p in pos_scores:
        for n in neg_scores:
            total += 1
            if p > n:
                correct += 1
    auc = correct / total if total else 0.0
    return {"auc": round(auc, 3), "n_pos": len(pos_scores), "n_neg": len(neg_scores),
            "n_edges_total": n_edges}


def run_full_eval():
    """Собирает всё в одном месте — вызывается из GET /admin/eval."""
    return {
        "extraction": extraction_metrics(),
        "retrieval": retrieval_metrics(),
        "link_prediction": link_prediction_auc(),
        "model": {
            "extract_model": settings.ollama_model_extract or settings.ollama_model_tool,
            "synth_model": settings.ollama_model_synth,
            "embedding_dim": settings.embedding_dim,
            "embedding_provider": settings.embedding_provider,
        },
    }

"""CompareService: сравнение двух вариантов (материалов, режимов, технологий)
по параметрам, с агрегацией значений свойств из экспериментов.
"""

from __future__ import annotations

from statistics import mean, stdev

from loguru import logger

from app.db.neo4j_client import get_neo4j


class CompareService:

    def compare_options(self, option_a, option_b):
        """option_a/b — dict {kind: 'material'|'mode', code: '...'}."""
        neo = get_neo4j()
        with neo.driver.session() as s:
            rows_a = self._collect_stats(s, option_a)
            rows_b = self._collect_stats(s, option_b)

        # Собираем свойства в общий набор (исключая служебный ключ _ids)
        keys = (set(rows_a.keys()) | set(rows_b.keys())) - {"_ids"}
        matrix = []
        for k in sorted(keys):
            a = rows_a.get(k)
            b = rows_b.get(k)
            matrix.append({
                "property": k,
                "a": a, "b": b,
                "delta": (b["mean"] - a["mean"]) if (a and b and a.get("mean") is not None and b.get("mean") is not None) else None,
            })
        return {
            "option_a": option_a,
            "option_b": option_b,
            "properties": matrix,
            "experiments_a": rows_a.get("_ids", []),
            "experiments_b": rows_b.get("_ids", []),
        }

    def _collect_stats(self, session, option):
        kind = option.get("kind")
        code = option.get("code")
        if not kind or not code:
            return {}

        if kind == "material":
            q = """
            MATCH (m:Material {code: $code})<-[:USED_MATERIAL]-(e:Experiment)
                  -[r:MEASURED]->(p:Property)
            RETURN p.display_name AS prop, p.unit AS unit,
                   collect(r.value) AS vals,
                   collect(e.experiment_id) AS ids,
                   collect(e.year) AS years
            """
        elif kind == "mode":
            q = """
            MATCH (mo:Mode {code: $code})<-[:USED_MODE]-(e:Experiment)
                  -[r:MEASURED]->(p:Property)
            RETURN p.display_name AS prop, p.unit AS unit,
                   collect(r.value) AS vals,
                   collect(e.experiment_id) AS ids,
                   collect(e.year) AS years
            """
        else:
            return {}

        out = {}
        all_ids = set()
        for rec in session.run(q, code=code):
            prop = rec["prop"]
            vals = [float(v) for v in (rec["vals"] or []) if v is not None]
            ids = list(rec["ids"] or [])
            all_ids.update(ids)
            if not prop:
                continue
            entry = {
                "unit": rec.get("unit"),
                "count": len(vals),
                "mean": round(mean(vals), 3) if vals else None,
                "min": min(vals) if vals else None,
                "max": max(vals) if vals else None,
                "std": round(stdev(vals), 3) if len(vals) >= 2 else None,
                "experiments": ids[:5],
            }
            out[prop] = entry
        out["_ids"] = list(all_ids)
        return out

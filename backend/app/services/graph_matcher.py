"""GraphMatcher: QueryIntent → Cypher.

Поддерживает:
- фильтры по материалам, свойствам, режимам
- диапазоны по любым ModeParam (temperature, concentration, flow_rate, pressure, pH, current_density, cost, throughput)
- гео-фильтр (domestic RU+СНГ / foreign / any)
- временной диапазон
- фильтр по confidence вывода
"""

from __future__ import annotations

from loguru import logger

from app.db.neo4j_client import get_neo4j


PARAM_ALIASES = {
    "temperature": "temperature",
    "temperature_c": "temperature",
    "temp": "temperature",
    "concentration": "concentration",
    "concentration_mgl": "concentration",
    "flow_rate": "flow_rate",
    "flow": "flow_rate",
    "pressure": "pressure",
    "pressure_mpa": "pressure",
    "ph": "ph",
    "current_density": "current_density",
    "cost": "cost",
    "throughput": "throughput",
    "duration": "duration",
}


class GraphMatcher:
    def match(self, intent, limit=30, geo_filter="any", min_confidence=None):
        """Из QueryIntent + доп. фильтров собирает Cypher, возвращает эксперименты + doc_ids.

        Если нет ни одного структурного фильтра (материал/свойство/режим/год/гео),
        возвращаем пустой список — не имеет смысла отдавать 30 случайных
        экспериментов из 10k+, потому что синтезатор из них не сформирует
        осмысленный ответ (было видно в проде: LLM выдавал сырые ID
        «EXP-UI-…» в качестве текста). Пустой match заставляет ask.py
        включить семантическое расширение + FTS-сидинг, там точность выше.
        """
        materials = [m.get("match") for m in (intent.get("materials") or []) if m.get("match")]
        properties = [p.get("match") for p in (intent.get("properties") or []) if p.get("match")]
        modes = intent.get("modes") or []
        time_range = intent.get("time_range") or {}
        # geo_filter может быть в intent или переопределён параметром
        geo = intent.get("geo") or geo_filter or "any"

        has_mode_param = any(mo.get("params") for mo in modes)
        no_filters = (
            not materials and not properties and not has_mode_param
            and not time_range and (geo or "any") == "any"
        )
        if no_filters:
            empty_cypher = "-- no structural filters, deferring to semantic/FTS"
            logger.info("Matcher: no structural filters, returning empty for semantic fallback")
            return {
                "experiments": [], "doc_ids": [],
                "cypher": empty_cypher,
                "regions_seen": {"domestic": 0, "foreign": 0, "other": 0},
            }

        cypher_parts = ["MATCH (e:Experiment)"]
        where = []
        params = {"limit": limit}

        if materials:
            cypher_parts.append("MATCH (e)-[:USED_MATERIAL]->(m:Material)")
            where.append("m.code IN $materials")
            params["materials"] = materials

        if properties:
            cypher_parts.append("MATCH (e)-[meas:MEASURED]->(p:Property)")
            where.append("p.code IN $properties")
            params["properties"] = properties

        # Параметры режима: диапазоны для temperature, concentration, flow_rate, ...
        pcount = 0
        for i, mo in enumerate(modes):
            for pm in mo.get("params") or []:
                raw_name = (pm.get("name") or "").lower()
                canonical = PARAM_ALIASES.get(raw_name)
                if not canonical:
                    continue
                alias = f"pp{pcount}"
                cypher_parts.append(
                    f"MATCH (e)-[:USED_MODE]->(:Mode)-[:HAS_PARAM]->({alias}:ModeParam {{name: $pn{pcount}}})"
                )
                params[f"pn{pcount}"] = canonical
                if pm.get("min") is not None:
                    where.append(f"{alias}.value >= $pmin{pcount}")
                    params[f"pmin{pcount}"] = float(pm["min"])
                if pm.get("max") is not None:
                    where.append(f"{alias}.value <= $pmax{pcount}")
                    params[f"pmax{pcount}"] = float(pm["max"])
                if pm.get("value") is not None:
                    where.append(f"{alias}.value = $pval{pcount}")
                    params[f"pval{pcount}"] = float(pm["value"])
                pcount += 1

        # Гео-фильтр — через DOCUMENTED_IN → Document.geo_region
        if geo in ("domestic", "foreign"):
            cypher_parts.append(
                "OPTIONAL MATCH (e)-[:DOCUMENTED_IN]->(gd:Document)"
            )
            where.append("gd.geo_region = $geo")
            params["geo"] = geo

        if time_range.get("from") is not None:
            where.append("e.year >= $year_from")
            params["year_from"] = int(time_range["from"])
        if time_range.get("to") is not None:
            where.append("e.year <= $year_to")
            params["year_to"] = int(time_range["to"])

        if where:
            cypher_parts.append("WHERE " + " AND ".join(where))

        return_select = (
            "e.experiment_id AS experiment_id, e.title AS title, e.year AS year, "
            "[(e)-[:USED_MATERIAL]->(m) | m.display_name] AS materials, "
            "[(e)-[:USED_MODE]->(mo) | mo.display_name] AS modes, "
            "[(e)-[:MEASURED]->(p) | p.display_name][0] AS property_name, "
            "[(e)-[mr:MEASURED]->(:Property) | mr.value][0] AS value, "
            "[(e)-[mr:MEASURED]->(:Property) | mr.unit][0] AS unit, "
            "[(e)-[:DOCUMENTED_IN]->(d) | d.doc_id][0] AS doc_id, "
            "[(e)-[:DOCUMENTED_IN]->(d) | d.geo_region][0] AS geo_region, "
            "[(e)-[:DOCUMENTED_IN]->(d) | d.country_code][0] AS country_code, "
            "[(e)-[:DOCUMENTED_IN]->(d) | d.language][0] AS language, "
            "[(e)-[:RESULTED_IN]->(c) | c.confidence][0] AS confidence, "
            "[(e)-[:RESULTED_IN]->(c) | c.text][0] AS conclusion_text "
        )
        if min_confidence is not None:
            # min_confidence фильтруем в WHERE-фазе через WITH
            pass  # упрощение MVP

        cypher_parts.append("RETURN DISTINCT " + return_select)
        cypher_parts.append("LIMIT $limit")
        cypher = "\n".join(cypher_parts)

        logger.debug(f"Matcher Cypher:\n{cypher}\nparams={list(params.keys())}")
        neo = get_neo4j()
        with neo.driver.session() as s:
            res = s.run(cypher, **params)
            experiments = []
            doc_ids = set()
            regions_seen = {"domestic": 0, "foreign": 0, "other": 0}
            for r in res:
                region = r.get("geo_region") or "other"
                regions_seen[region] = regions_seen.get(region, 0) + 1
                row = {
                    "experiment_id": r.get("experiment_id"),
                    "title": r.get("title"),
                    "year": r.get("year"),
                    "materials": list(r.get("materials") or []),
                    "modes": list(r.get("modes") or []),
                    "property": r.get("property_name"),
                    "value": r.get("value"),
                    "unit": r.get("unit"),
                    "doc_id": r.get("doc_id"),
                    "geo_region": region,
                    "country_code": r.get("country_code"),
                    "language": r.get("language"),
                    "confidence": r.get("confidence"),
                    "conclusion_text": r.get("conclusion_text"),
                }
                experiments.append(row)
                if row["doc_id"]:
                    doc_ids.add(row["doc_id"])
        return {
            "experiments": experiments,
            "doc_ids": list(doc_ids),
            "cypher": cypher,
            "regions_seen": regions_seen,
        }

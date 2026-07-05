"""VersioningService: версионирование фактов (ТЗ).

Один и тот же материал × процесс × свойство измеряется в разных экспериментах,
разными годами, разными командами — и цифры не совпадают. Раньше в ответе
всплывал случайный эксперимент, а без даты пользователь не понимал, актуальна
цифра или устарела.

Сервис:
- проставляет на каждом MEASURED поле `valid_from` (берётся из `experiment.date`
  или `experiment.year`), чтобы фронт мог сортировать факты по времени;
- размечает актуальный факт `is_current=true` в рамках (material, property);
  предыдущие получают `is_current=false` и SUPERSEDED_BY-ребро;
- отдаёт историю версий по паре (material, property).
"""

from __future__ import annotations

from loguru import logger

from app.db.neo4j_client import get_neo4j


class VersioningService:
    def _write_valid_from(self):
        """Проставить valid_from на MEASURED там, где его ещё нет."""
        q = """
        MATCH (e:Experiment)-[r:MEASURED]->(:Property)
        WHERE r.valid_from IS NULL
        WITH r, e,
             coalesce(e.date,
                      CASE WHEN e.year IS NOT NULL
                           THEN toString(e.year) + '-01-01'
                           ELSE NULL END) AS vf
        WHERE vf IS NOT NULL
        SET r.valid_from = vf
        RETURN count(r) AS updated
        """
        with get_neo4j().driver.session() as s:
            rec = s.run(q).single()
            return int(rec["updated"] or 0)

    def _mark_current_versions(self):
        """Для каждой пары (material, property) оставить is_current=true у самой
        свежей записи MEASURED. Более старые получают is_current=false и
        SUPERSEDED_BY-ребро к самой новой (пропуская промежуточные, чтобы не
        разводить лишние рёбра).

        Двухпроходная реализация: в Cypher нельзя обратиться к вложенным
        свойствам map-элементов (x.e не работает), поэтому сперва выбираем id
        новейшего эксперимента для каждой пары, потом отдельно проставляем
        is_current и клеим ребро SUPERSEDED_BY.
        """
        q_newest = """
        MATCH (m:Material)<-[:USED_MATERIAL]-(e:Experiment)-[r:MEASURED]->(p:Property)
        WITH m, p, e, r,
             coalesce(r.valid_from,
                      e.date,
                      CASE WHEN e.year IS NOT NULL THEN toString(e.year) + '-01-01' END) AS ts
        WHERE ts IS NOT NULL
        WITH m, p, collect({eid: e.experiment_id, ts: ts}) AS entries
        WHERE size(entries) > 1
        WITH m, p, entries,
             reduce(best = entries[0], x IN entries |
                    CASE WHEN x.ts > best.ts THEN x ELSE best END) AS newest
        RETURN m.code AS m_code, p.code AS p_code,
               newest.eid AS newest_eid, newest.ts AS newest_ts
        """
        pairs = []
        with get_neo4j().driver.session() as s:
            for row in s.run(q_newest):
                pairs.append({
                    "m_code": row["m_code"], "p_code": row["p_code"],
                    "newest_eid": row["newest_eid"], "newest_ts": row["newest_ts"],
                })

            chained = 0
            for pair in pairs:
                # is_current = true у новейшего замера, false у остальных
                s.run(
                    """
                    MATCH (m:Material {code:$m})<-[:USED_MATERIAL]-(e:Experiment)
                          -[r:MEASURED]->(p:Property {code:$p})
                    WITH e, r, $newest AS newest
                    SET r.is_current = (e.experiment_id = newest)
                    """,
                    m=pair["m_code"], p=pair["p_code"], newest=pair["newest_eid"],
                )
                res = s.run(
                    """
                    MATCH (m:Material {code:$m})<-[:USED_MATERIAL]-(e:Experiment)
                          -[:MEASURED]->(p:Property {code:$p})
                    MATCH (newest:Experiment {experiment_id: $newest})
                    WHERE e.experiment_id <> $newest
                    MERGE (e)-[:SUPERSEDED_BY {reason: 'version-newer-measurement'}]->(newest)
                    RETURN count(*) AS n
                    """,
                    m=pair["m_code"], p=pair["p_code"], newest=pair["newest_eid"],
                )
                chained += int(res.single()["n"] or 0)
        return chained

    def apply(self):
        """Запускает обе фазы: valid_from + is_current + SUPERSEDED_BY."""
        stamped = self._write_valid_from()
        chained = self._mark_current_versions()
        logger.info(
            f"VersioningService: valid_from stamped on {stamped} MEASURED, "
            f"{chained} SUPERSEDED_BY chains built"
        )
        return {"valid_from_stamped": stamped, "superseded_by_chained": chained}

    def history(self, material_code, property_code, limit=50):
        """История версий факта (material × property): список замеров,
        отсортированный от новейшего к самому старому."""
        q = """
        MATCH (m:Material {code: $mc})<-[:USED_MATERIAL]-(e:Experiment)
              -[r:MEASURED]->(p:Property {code: $pc})
        OPTIONAL MATCH (e)-[:DOCUMENTED_IN]->(d:Document)
        OPTIONAL MATCH (e)-[:USED_MODE]->(mo:Mode)
        WITH m, p, e, r, d,
             collect(DISTINCT coalesce(mo.display_name, mo.code))[..3] AS modes,
             coalesce(r.valid_from, e.date,
                      CASE WHEN e.year IS NOT NULL THEN toString(e.year) + '-01-01' END) AS ts
        RETURN
          m.display_name AS material_name,
          p.display_name AS property_name,
          coalesce(p.unit, r.unit) AS unit,
          collect({
            experiment_id: e.experiment_id,
            title: e.title,
            valid_from: ts,
            value: r.value,
            unit: coalesce(r.unit, p.unit),
            is_current: coalesce(r.is_current, false),
            doc_id: d.doc_id, doc_title: d.title,
            modes: modes,
            confidence: e.confidence
          })[..$lim] AS versions
        """
        with get_neo4j().driver.session() as s:
            rec = s.run(q, mc=material_code, pc=property_code, lim=int(limit)).single()
        if not rec:
            return {"material": material_code, "property": property_code, "versions": []}
        versions = rec["versions"] or []
        versions.sort(key=lambda v: (v.get("valid_from") or ""), reverse=True)
        return {
            "material": material_code,
            "material_name": rec["material_name"],
            "property": property_code,
            "property_name": rec["property_name"],
            "unit": rec["unit"],
            "versions": versions,
        }

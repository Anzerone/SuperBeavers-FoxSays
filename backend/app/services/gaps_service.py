"""GapsService: тепловая карта покрытия (data gaps) + структурные пробелы (link prediction).

Матрица data_gaps: Y = материалы (топ по частоте), X = процессы (Mode.category
или имя режима, если категорий нет). Ячейка — количество Experiment, где
одновременно используются этот материал и хотя бы один Mode этой категории.
Мусорные записи-«осколки» словаря («не определено», пустые названия) — отсекаются.
"""

from __future__ import annotations

from loguru import logger

from app.db.neo4j_client import get_neo4j


# Строки, которые никогда не должны попадать в оси матрицы (мусор из NER).
_GARBAGE_TOKENS = {"не определено", "не определен", "unknown", "none", "n/a", "-", ""}


def _looks_garbage(name):
    if not name:
        return True
    return str(name).strip().lower() in _GARBAGE_TOKENS


class GapsService:
    # In-memory кэш матрицы data_gaps на 30 сек: пересобирать её на каждом
    # рендере страницы дорого (3 сканирования Experiment/Material/Mode на 10k+
    # узлов), а меняется медленно — по мере фонового enrichment'а. Ключ учитывает
    # оси и фильтр по свойству, потому что все три параметра формируют разные
    # выборки.
    _matrix_cache: dict = {}
    _matrix_ttl_s = 30.0

    def data_gaps_matrix(self, y_axis="material", x_axis="process",
                        property_code=None, top_materials=10, top_processes=12):
        """Матрица Материал × Процесс.

        rows — до top_materials материалов с наибольшим числом экспериментов;
        cols — до top_processes процессов (Mode.category, fallback Mode.display_name);
        counts[i][j] — сколько Experiment используют одновременно rows[i] и cols[j].
        """
        import time as _time
        key = (int(top_materials), int(top_processes), property_code or "")
        cached = self._matrix_cache.get(key)
        now = _time.time()
        if cached and now - cached["ts"] < self._matrix_ttl_s:
            return cached["data"]

        neo = get_neo4j()
        garbage = list(_GARBAGE_TOKENS)
        with neo.driver.session() as s:
            # Один round-trip: сначала top-N материалов, потом top-M процессов,
            # потом матрицу — всё это одним query через WITH-цепочку. Раньше было
            # 3 отдельных session.run с двумя лишними round-trip'ами.
            where_prop = ""
            params = {
                "top_m": int(top_materials),
                "top_p": int(top_processes),
                "garbage": garbage,
            }
            if property_code:
                where_prop = ("AND EXISTS { MATCH (e)-[:MEASURED]->"
                              "(:Property {code: $pc}) }")
                params["pc"] = property_code

            q = f"""
            CALL {{
              MATCH (m:Material)<-[:USED_MATERIAL]-(e:Experiment)
              WHERE m.display_name IS NOT NULL
                AND trim(m.display_name) <> ''
                AND NOT toLower(trim(m.display_name)) IN $garbage
              RETURN m, count(DISTINCT e) AS c
              ORDER BY c DESC LIMIT $top_m
            }}
            WITH collect({{code: m.code, name: coalesce(m.display_name, m.code)}}) AS rows_raw
            CALL {{
              MATCH (mo:Mode)<-[:USED_MODE]-(e:Experiment)
              WITH coalesce(mo.category, mo.display_name, mo.code) AS proc,
                   count(DISTINCT e) AS c
              WHERE proc IS NOT NULL AND trim(proc) <> ''
                AND NOT toLower(trim(proc)) IN $garbage
              RETURN proc, c ORDER BY c DESC LIMIT $top_p
            }}
            WITH rows_raw, collect({{code: proc, label: proc}}) AS cols_raw
            WITH rows_raw, cols_raw,
                 [r IN rows_raw | r.code] AS mat_codes,
                 [c IN cols_raw | c.code] AS proc_codes
            CALL {{
              WITH mat_codes, proc_codes
              MATCH (m:Material)<-[:USED_MATERIAL]-(e:Experiment)-[:USED_MODE]->(mo:Mode)
              WITH m, e, coalesce(mo.category, mo.display_name, mo.code) AS proc,
                   mat_codes, proc_codes
              WHERE m.code IN mat_codes AND proc IN proc_codes {where_prop}
              RETURN m.code AS mat, proc AS process,
                     count(DISTINCT e) AS c,
                     collect(DISTINCT e.experiment_id)[..3] AS examples
            }}
            RETURN rows_raw, cols_raw,
                   collect({{mat: mat, process: process, c: c, examples: examples}}) AS cells
            """
            rec = s.run(q, **params).single()

        rows_raw = (rec and rec["rows_raw"]) or []
        cols_raw = (rec and rec["cols_raw"]) or []
        cells = (rec and rec["cells"]) or []

        rows = [{"code": r["code"], "name": r["name"] or r["code"]} for r in rows_raw]
        cols = [{"code": c["code"], "label": c["label"]} for c in cols_raw]

        if not rows or not cols:
            result = {
                "rows": rows, "cols": cols,
                "counts": [[0] * len(cols) for _ in rows],
                "cell_examples": {}, "property_code": property_code,
                "axes": {"y": "material", "x": "process"},
            }
            self._matrix_cache[key] = {"ts": now, "data": result}
            return result

        counts_map = {(c["mat"], c["process"]): c["c"] for c in cells}
        examples_map = {(c["mat"], c["process"]): c["examples"] for c in cells}

        counts = []
        cell_examples = {}
        for r in rows:
            row_counts = []
            for ci, c in enumerate(cols):
                k2 = (r["code"], c["code"])
                cnt = counts_map.get(k2, 0)
                row_counts.append(cnt)
                if cnt:
                    cell_examples[f"{r['code']}|{ci}"] = examples_map.get(k2, [])
            counts.append(row_counts)

        result = {
            "rows": rows,
            "cols": cols,
            "counts": counts,
            "cell_examples": cell_examples,
            "property_code": property_code,
            "axes": {"y": "material", "x": "process"},
        }
        self._matrix_cache[key] = {"ts": now, "data": result}
        return result

    def structural_gaps(self, limit=30):
        """Пробелы через link prediction (Adamic-Adar).

        Раньше делали картезианский join `MATCH (a:Experiment), (b:Experiment)`
        — на корпусе 10k+ экспериментов это ~100 млн пар, GDS.adamicAdar считал
        на каждой, фронт минуту висел на «Загружаем...». Теперь берём только те
        пары, что уже имеют общего соседа (Material/Mode/Property) — этих пар
        обычно в сотни раз меньше, и мы сразу отсеиваем всё, где Adamic-Adar
        точно = 0. Ограничение `size(nbrs) BETWEEN 2 AND 40` отсекает
        случайные шумовые связи и хабы вроде «температура», где N² взрывается.
        """
        neo = get_neo4j()
        try:
            with neo.driver.session() as s:
                res = list(s.run("""
                MATCH (a:Experiment)-[:USED_MATERIAL|USED_MODE|MEASURED]->(shared)
                      <-[:USED_MATERIAL|USED_MODE|MEASURED]-(b:Experiment)
                WHERE elementId(a) < elementId(b)
                  AND NOT (a)-[:SIMILAR_TO]-(b)
                WITH DISTINCT a, b LIMIT 5000
                MATCH (a)-[:USED_MATERIAL|USED_MODE|MEASURED]->(shared)
                      <-[:USED_MATERIAL|USED_MODE|MEASURED]-(b)
                OPTIONAL MATCH (shared)<-[:USED_MATERIAL|USED_MODE|MEASURED]-(nbr:Experiment)
                WITH a, b, shared, count(DISTINCT nbr) AS deg
                WHERE deg >= 2 AND deg <= 40
                // toFloat: без каста log(int) в Neo4j 5.x иногда даёт 0
                // → sum = 0 → WHERE score > 0.3 отсеивает всё.
                WITH a, b, sum(1.0 / log(toFloat(deg))) AS score
                WHERE score > 0.3
                RETURN a.experiment_id AS a_id, a.title AS a_title,
                       b.experiment_id AS b_id, b.title AS b_title, score
                ORDER BY score DESC LIMIT $lim
                """, lim=limit))
            return [
                {"a_id": r["a_id"], "a_title": r["a_title"],
                 "b_id": r["b_id"], "b_title": r["b_title"], "score": r["score"]}
                for r in res
            ]
        except Exception as e:
            logger.warning(f"structural_gaps failed: {e}")
            return []

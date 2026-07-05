"""NormalizeService: чистит авто-извлечённые сущности графа.

Проблема из прода: экстрактор создаёт узлы `Material {code: "MAT-EXT-XXXXX"}`,
у которых `display_name` иногда попадает как чужой код (например
`MAT-CU-METAL`) — пользователь в UI видит непонятный «MAT-CU-METAL» вместо
«Медь металлическая». А иногда несколько MAT-EXT-… ссылаются на один и тот же
канонический термин (МПГ, МКФФ) и в матрице пробелов появляются дубли.

Сервис проходит по всем `MAT-EXT-*`, ищет соответствие в словаре и:
- прописывает нормальный display_name + description + family/base_element;
- если каноничный код есть в словаре, вешает ребро SUPERSEDED_BY
  (используется системой версионирования фактов).
"""

from __future__ import annotations

from loguru import logger

from app.db.neo4j_client import get_neo4j
from app.services import dictionary


class NormalizeService:
    def _lookup_by_alias(self, name):
        code = dictionary.lookup_material(name)
        if code:
            return dictionary.get_material(code)
        # Fallback fuzzy: display_name может отличаться в 1-2 символах
        # (Cyrillic е/ё, лишние пробелы) — rapidfuzz это ловит.
        entry = dictionary.fuzzy_lookup_material(name, threshold=90)
        return entry

    def normalize_materials(self, dry_run=False):
        """Проходит по MAT-EXT-* и подтягивает display_name/description из словаря.

        Возвращает {scanned, updated, aliased, examples}.
        """
        neo = get_neo4j()
        stats = {"scanned": 0, "updated": 0, "aliased": 0, "examples": []}

        with neo.driver.session() as s:
            rows = list(s.run(
                "MATCH (m:Material) WHERE m.code STARTS WITH 'MAT-EXT-' "
                "RETURN m.code AS code, m.display_name AS name, m.description AS descr"
            ))
            stats["scanned"] = len(rows)

            for row in rows:
                code = row["code"]
                current_name = row["name"] or code
                current_descr = row["descr"]

                candidates = [current_name]
                if current_name != code:
                    candidates.append(code)

                canonical = None
                for cand in candidates:
                    if not cand:
                        continue
                    canonical = self._lookup_by_alias(cand)
                    if canonical:
                        break

                if not canonical:
                    continue

                new_name = canonical.get("display_name") or current_name
                new_descr = (canonical.get("meta") or {}).get("description") or current_descr
                fam = (canonical.get("meta") or {}).get("family")
                be = (canonical.get("meta") or {}).get("base_element")
                canonical_code = canonical.get("code")

                needs_name = new_name != current_name
                needs_descr = bool(new_descr) and new_descr != current_descr
                if not (needs_name or needs_descr or fam or be):
                    continue

                if not dry_run:
                    s.run(
                        "MATCH (m:Material {code: $c}) "
                        "SET m.display_name = $n, "
                        "    m.description = coalesce($d, m.description), "
                        "    m.family = coalesce($fam, m.family), "
                        "    m.base_element = coalesce($be, m.base_element), "
                        "    m.aliases = coalesce(m.aliases, []) + $cc, "
                        "    m.normalized_at = datetime()",
                        c=code, n=new_name, d=new_descr, fam=fam, be=be, cc=[canonical_code],
                    )
                    # Ребро SUPERSEDED_BY между извлечённым и каноническим — если
                    # каноническая нода тоже есть в графе. Иначе просто держим alias.
                    canon_exists = s.run(
                        "MATCH (m:Material {code: $c}) RETURN count(m) AS n",
                        c=canonical_code,
                    ).single()["n"]
                    if canon_exists:
                        s.run(
                            "MATCH (old:Material {code: $old}), (new:Material {code: $new}) "
                            "MERGE (old)-[:SUPERSEDED_BY {reason: 'dictionary-normalize'}]->(new)",
                            old=code, new=canonical_code,
                        )
                        stats["aliased"] += 1

                stats["updated"] += 1
                if len(stats["examples"]) < 20:
                    stats["examples"].append({
                        "code": code, "was": current_name, "now": new_name,
                        "canonical": canonical_code,
                    })

        logger.info(
            f"NormalizeService: scanned={stats['scanned']} updated={stats['updated']} "
            f"aliased={stats['aliased']}"
        )
        return stats

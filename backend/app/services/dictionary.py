"""Нормализация и поиск синонимов для материалов, режимов, свойств.

Подгружает справочники из data/raw/dicts/ (если есть) и держит в памяти
inverse-индекс синонимов → каноничный код.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from loguru import logger

# Канонические словари: code -> {display_name, aliases:list, meta}
_materials: dict = {}
_properties: dict = {}
_modes: dict = {}
_equipment: dict = {}
# Инверсные индексы для быстрого поиска по любому синониму
_material_index: dict = {}
_property_index: dict = {}
_mode_index: dict = {}
_equipment_index: dict = {}


def _norm(s):
    """Нормализация строки: lowercase, ASCII-сворачивание, убираем пробелы/дефисы."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    # убираем дублирующиеся пробелы и спец-символы кроме букв/цифр/дефиса
    s = re.sub(r"[\s\-_/.,;]+", "", s)
    return s


def _add(canon_map, idx, code, display_name, aliases=None, meta=None):
    aliases = aliases or []
    canon_map[code] = {
        "code": code,
        "display_name": display_name,
        "aliases": list(aliases),
        "meta": meta or {},
    }
    for key in [code, display_name] + list(aliases):
        idx[_norm(key)] = code


def load_dictionaries(dicts_dir):
    """Загружает CSV-словари. Колонки: code, display_name, aliases (через ; ), [meta cols]."""
    import pandas as pd

    p = Path(dicts_dir)
    if not p.exists():
        logger.info(f"Dictionary dir not found: {p} — skipping")
        return

    def _load_csv(path, canon, idx, extra_meta=None):
        if not Path(path).exists():
            return 0
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            code = str(row.get("code") or row.get("display_name") or "").strip()
            if not code:
                continue
            disp = str(row.get("display_name") or code).strip()
            aliases_raw = row.get("aliases")
            aliases = []
            if isinstance(aliases_raw, str) and aliases_raw:
                aliases = [a.strip() for a in re.split(r"[;,|]", aliases_raw) if a.strip()]
            meta = {}
            for col in extra_meta or []:
                if col in row and not (isinstance(row[col], float) and str(row[col]) == "nan"):
                    meta[col] = row[col]
            _add(canon, idx, code, disp, aliases, meta)
        return len(df)

    n_m = _load_csv(p / "materials.csv", _materials, _material_index,
                    extra_meta=["family", "base_element", "gost", "description"])
    n_p = _load_csv(p / "properties.csv", _properties, _property_index,
                    extra_meta=["unit", "category", "description"])
    n_mo = _load_csv(p / "modes.csv", _modes, _mode_index,
                    extra_meta=["category", "description"])
    n_eq = _load_csv(p / "equipment.csv", _equipment, _equipment_index,
                    extra_meta=["type", "description"])
    logger.info(
        f"Dictionaries loaded: {n_m} materials, {n_p} properties, {n_mo} modes, {n_eq} equipment"
    )


def lookup_material(text):
    """Возвращает каноничный код по любому синониму или None."""
    return _material_index.get(_norm(text))


def lookup_property(text):
    return _property_index.get(_norm(text))


def lookup_mode(text):
    return _mode_index.get(_norm(text))


def lookup_equipment(text):
    return _equipment_index.get(_norm(text))


def pattern_prefilter(text):
    """Быстрый pattern-matching до LLM (в стиле spaCy EntityRuler):
    ищет в тексте прямые вхождения известных материалов/режимов/свойств
    и возвращает первый структурный «кандидат» {material, mode, property}.
    Если нашли хотя бы 2 из 3 полей — LLM можно НЕ звать (экономит ~30 сек).
    """
    if not text:
        return None
    low = _norm(text)
    if not low:
        return None

    def _first_hit(index_dict, entities):
        # Ищем самое ДЛИННОЕ совпадение — приоритет специфичным терминам.
        best = None
        best_len = 0
        for key, code in index_dict.items():
            if not key or len(key) < 3:
                continue
            if key in low and len(key) > best_len:
                ent = entities.get(code) or {}
                best = {"code": code, "display_name": ent.get("display_name")}
                best_len = len(key)
        return best

    hit = {
        "material": _first_hit(_material_index, _materials),
        "mode":     _first_hit(_mode_index, _modes),
        "property": _first_hit(_property_index, _properties),
    }
    n_hits = sum(1 for v in hit.values() if v)
    if n_hits < 2:
        return None
    return {
        "material": (hit["material"] or {}).get("display_name") or (hit["material"] or {}).get("code"),
        "mode":     (hit["mode"] or {}).get("display_name") or (hit["mode"] or {}).get("code"),
        "property": (hit["property"] or {}).get("display_name") or (hit["property"] or {}).get("code"),
        "conclusion": None, "value": None, "unit": None,
        "confidence": 0.65 if n_hits == 2 else 0.75,
        "_prefilter": True,
    }


def fuzzy_lookup_material(text, threshold=88):
    """Fuzzy-match через rapidfuzz по нормализованным ключам."""
    from rapidfuzz import process, fuzz
    norm = _norm(text)
    if not norm:
        return None
    keys = list(_material_index.keys())
    if not keys:
        return None
    match, score, _ = process.extractOne(norm, keys, scorer=fuzz.ratio)
    if score >= threshold:
        return _material_index[match]
    return None


def get_material(code):
    return _materials.get(code)


def get_property(code):
    return _properties.get(code)


def get_mode(code):
    return _modes.get(code)


def get_equipment(code):
    return _equipment.get(code)


def all_materials():
    return list(_materials.values())


def all_properties():
    return list(_properties.values())


def all_modes():
    return list(_modes.values())


def all_equipment():
    return list(_equipment.values())


def register_material(code, display_name, aliases=None, meta=None):
    """Добавить материал во время ingest, если его нет в словаре."""
    if code not in _materials:
        _add(_materials, _material_index, code, display_name, aliases, meta)


def register_property(code, display_name, aliases=None, meta=None):
    if code not in _properties:
        _add(_properties, _property_index, code, display_name, aliases, meta)


def register_mode(code, display_name, aliases=None, meta=None):
    if code not in _modes:
        _add(_modes, _mode_index, code, display_name, aliases, meta)


def register_equipment(code, display_name, aliases=None, meta=None):
    if code not in _equipment:
        _add(_equipment, _equipment_index, code, display_name, aliases, meta)

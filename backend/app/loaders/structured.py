"""Loader структурированного корпуса + доменный парсер параметров режимов.

Понимает: температуру, длительность, давление, концентрацию, скорость потока,
pH, плотность тока, стоимость, производительность (throughput).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger

from app.services import dictionary


def _split_codes(value):
    if pd.isna(value) or value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    return [x.strip() for x in re.split(r"[;,|]", s) if x.strip()]


def _norm_value(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


# =========================================================================
# Парсер режима — доменные числовые параметры
# =========================================================================

def parse_mode_string(text):
    """Извлекает из свободной строки режима атомарные числовые параметры.

    Расширенный набор для металлургии/гидрометаллургии:
    - temperature_c, duration_h, pressure (МПа/атм/bar)
    - concentration_mgl (мг/л, г/л → мг/л), concentration_gl
    - flow_rate_m3h (м³/ч, л/с → м³/ч)
    - ph_value, current_density_am2 (А/м², А/дм²)
    - cost_rub, throughput_tday (т/сут, т/год → т/сут)
    """
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    low = s.lower().replace(",", ".")
    out = {"raw": s, "display_name": s}

    # === Температура ===
    # диапазон «1100-1200 °C» проверяем ПЕРВЫМ, иначе дефис принимается за
    # знак минуса и «1100-1200 °C» ошибочно читается как -1200.
    rng = re.search(r"(\d{2,5})\s*[-–—]\s*(\d{2,5})\s*°?\s*[cс]\b", low)
    if rng:
        out["temperature_c"] = (int(rng.group(1)) + int(rng.group(2))) / 2
    else:
        t = re.search(r"(-?\d{1,4}(?:\.\d+)?)\s*°?\s*[cс]\b", low)
        if t:
            out["temperature_c"] = float(t.group(1))

    # === Длительность ===
    dur = re.search(r"(\d{1,4}(?:\.\d+)?)\s*(ч|час|hr?|hour)", low)
    if dur:
        out["duration_h"] = float(dur.group(1))
    else:
        dur_min = re.search(r"(\d{1,4}(?:\.\d+)?)\s*мин", low)
        if dur_min:
            out["duration_h"] = float(dur_min.group(1)) / 60

    # === Давление ===
    pr = re.search(r"(\d+(?:\.\d+)?)\s*(мпа|mpa|атм|atm|bar|бар)", low)
    if pr:
        val = float(pr.group(1))
        unit = pr.group(2).lower()
        # приводим к МПа
        if unit in ("атм", "atm"):
            val = val * 0.101325
        elif unit in ("bar", "бар"):
            val = val * 0.1
        out["pressure_mpa"] = round(val, 3)

    # === Концентрация ===
    # ищем «X мг/л» или «X г/л»
    conc = re.search(r"(\d+(?:\.\d+)?)\s*(мг|mg|г|g)\s*/\s*(л|l|дм)", low)
    if conc:
        val = float(conc.group(1))
        unit_num = conc.group(2)
        if unit_num in ("г", "g"):
            val = val * 1000  # → мг/л
        out["concentration_mgl"] = val
    # диапазон «200-300 мг/л»
    conc_rng = re.search(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(мг|г)\s*/\s*(л|дм)", low)
    if conc_rng:
        lo = float(conc_rng.group(1)); hi = float(conc_rng.group(2))
        val = (lo + hi) / 2
        if conc_rng.group(3) in ("г",):
            val *= 1000
        out["concentration_mgl"] = val

    # === Скорость потока ===
    flow = re.search(r"(\d+(?:\.\d+)?)\s*(м3|м³|m3|m\^3)\s*/\s*(ч|час|h)", low)
    if flow:
        out["flow_rate_m3h"] = float(flow.group(1))
    else:
        flow_ls = re.search(r"(\d+(?:\.\d+)?)\s*л\s*/\s*с", low)
        if flow_ls:
            out["flow_rate_m3h"] = float(flow_ls.group(1)) * 3.6

    # === pH ===
    ph = re.search(r"\bph\s*[=:]?\s*(\d+(?:\.\d+)?)", low)
    if ph:
        out["ph_value"] = float(ph.group(1))

    # === Плотность тока ===
    cd = re.search(r"(\d+(?:\.\d+)?)\s*а\s*/\s*(м2|м²|m2|дм2|дм²)", low)
    if cd:
        val = float(cd.group(1))
        if cd.group(2) in ("дм2", "дм²"):
            val = val * 100  # А/дм² → А/м²
        out["current_density_am2"] = val

    # === Экономические показатели ===
    cost = re.search(r"(\d+(?:\.\d+)?)\s*(руб|₽|rub|тыс[.\s]*руб|млн[.\s]*руб)", low)
    if cost:
        val = float(cost.group(1))
        unit = cost.group(2)
        if "тыс" in unit:
            val *= 1000
        elif "млн" in unit:
            val *= 1_000_000
        out["cost_rub"] = val

    # === Производительность (throughput) ===
    thr = re.search(r"(\d+(?:\.\d+)?)\s*т\s*/\s*(сут|день|day)", low)
    if thr:
        out["throughput_tday"] = float(thr.group(1))
    else:
        thr_y = re.search(r"(\d+(?:\.\d+)?)\s*т\s*/\s*(год|year|y)", low)
        if thr_y:
            out["throughput_tday"] = float(thr_y.group(1)) / 365

    # === Название процесса — первое слово ===
    first = re.match(r"^([А-Яа-яA-Za-z]+)", s)
    if first:
        out["name"] = first.group(1).lower()

    return out


def load_corpus(corpus_dir):
    p = Path(corpus_dir)
    if not p.exists():
        raise FileNotFoundError(f"Corpus dir not found: {p}")

    dictionary.load_dictionaries(p / "dicts")

    staff = _read_table(p / "staff.csv")
    teams = _read_table(p / "teams.csv")
    experiments = _read_table(p / "experiments.xlsx") or _read_table(p / "experiments.csv")
    if experiments is None or experiments.empty:
        logger.warning("experiments table missing")
        experiments = pd.DataFrame()

    logger.info(
        f"Corpus: {len(experiments)} exp, "
        f"{len(staff) if staff is not None else 0} authors, "
        f"{len(teams) if teams is not None else 0} teams"
    )
    return {
        "experiments": experiments,
        "staff": staff if staff is not None else pd.DataFrame(),
        "teams": teams if teams is not None else pd.DataFrame(),
    }


def _read_table(path):
    if not Path(path).exists():
        return None
    if str(path).endswith(".xlsx"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def iter_experiments(experiments_df):
    for _, row in experiments_df.iterrows():
        exp_id = str(_norm_value(row.get("experiment_id")) or "").strip()
        if not exp_id:
            continue
        yield {
            "experiment_id": exp_id,
            "title": str(_norm_value(row.get("title")) or exp_id),
            "description": str(_norm_value(row.get("description")) or ""),
            "year": int(row["year"]) if pd.notna(row.get("year")) else None,
            "date": str(_norm_value(row.get("date")) or "") or None,
            "material_codes": _split_codes(row.get("material_codes")),
            "mode_codes": _split_codes(row.get("mode_codes")),
            "equipment_codes": _split_codes(row.get("equipment_codes")),
            "author_ids": _split_codes(row.get("author_ids")),
            "team_id": str(_norm_value(row.get("team_id")) or "") or None,
            "document_id": str(_norm_value(row.get("document_id")) or "") or None,
            "tag_codes": _split_codes(row.get("tag_codes")),
            "property_code": _norm_value(row.get("property_code")),
            "property_value": float(row["property_value"]) if pd.notna(row.get("property_value")) else None,
            "property_unit": _norm_value(row.get("property_unit")),
            "conclusion_text": str(_norm_value(row.get("conclusion_text")) or "") or None,
        }

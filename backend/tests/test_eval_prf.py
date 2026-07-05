"""Offline-регрессия P/R/F1 для extraction без Neo4j/Ollama.

Gold — `backend/tests/fixtures/labeled_snippets.jsonl` (6 demo-экспериментов
из `data/corpus/experiments.csv`, размечены руками).

Pred — синтетические выходы экстрактора qwen2.5:3b с реалистичным шумом:
частичные совпадения по подстроке, пропуски полей, единичные false positive.
Дают baseline-число, к которому можно возвращаться при рефакторинге промптов.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.eval_service import _prf


FIXTURES = Path(__file__).parent / "fixtures"


def _load_gold() -> dict[str, dict]:
    gold = {}
    for line in (FIXTURES / "labeled_snippets.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        gold[rec["exp_id"]] = rec.get("gold") or {}
    return gold


# Синтетические предикты — что бы выдал экстрактор с точностью ~0.85 F1.
# Специально смоделирован разный шум: канонические подстроки (образец A1 ⊂
# Материал A1), пропуски полей, лишние поля где gold пуст.
SYNTHETIC_PRED = {
    "EXP-2024-001": {
        "material": "A1",
        "mode": "отжиг при 900 °C",
        "property": "прочность на разрыв",
    },
    "EXP-2024-002": {
        "material": "A1",               # "A1" ⊂ "Материал A1" → TP
        "mode": None,                   # gold есть, pred нет → FN
        "property": "прочность",        # gold.property = null, pred непусто → FP
    },
    "EXP-2024-003": {
        "material": "A2",
        "mode": "отжиг",
        "property": None,               # gold есть, pred нет → FN
    },
    "EXP-2024-004": {
        "material": "Р1",
        "mode": "электролиз",
        "property": "выход по току",
    },
    "EXP-2024-005": {
        "material": "Р1",
        "mode": "электролиз при 80 °C",
        "property": "выход",            # gold: "выход по току" ⊃ "выход" → TP
    },
    "EXP-2023-010": {
        "material": None,               # FN
        "mode": "отжиг",                # gold.mode = null → FP
        "property": "прочность после отжига",
    },
}


def test_prf_shape():
    gold = _load_gold()
    assert set(gold) == set(SYNTHETIC_PRED), "разметка и предикты должны покрывать один набор exp_id"
    for eid, g in gold.items():
        assert set(g) >= {"material", "mode", "property"}, f"{eid}: не все 3 поля в gold"


def test_prf_baseline():
    """Baseline P/R/F1 на синтетических предиктах.

    Ручной расчёт по 18 полям (6 exp × 3 field):
      TP=13, FP=2, FN=3
      Precision = 13/(13+2) = 0.8667
      Recall    = 13/(13+3) = 0.8125
      F1        = 2·P·R/(P+R) ≈ 0.8387
    """
    gold = _load_gold()
    prec, rec, f1, tp = _prf(gold, SYNTHETIC_PRED)

    assert tp == 13, f"ожидалось TP=13, получено {tp}"
    assert prec == pytest.approx(0.867, abs=1e-3), f"P={prec}"
    assert rec == pytest.approx(0.813, abs=1e-3), f"R={rec}"
    assert f1 == pytest.approx(0.839, abs=1e-3), f"F1={f1}"

    # Приёмочные пороги — если баланс шума в SYNTHETIC_PRED поменяют,
    # тест не сломается пока baseline держится.
    assert prec >= 0.80
    assert rec >= 0.75
    assert f1 >= 0.80


def test_prf_perfect_predictions():
    """Санити: если pred == gold, P=R=F1=1.0."""
    gold = _load_gold()
    prec, rec, f1, _ = _prf(gold, gold)
    assert prec == 1.0
    assert rec == 1.0
    assert f1 == 1.0


def test_prf_empty_predictions():
    """Санити: полностью пустой pred → P=R=F1=0."""
    gold = _load_gold()
    empty = {eid: {} for eid in gold}
    prec, rec, f1, tp = _prf(gold, empty)
    assert tp == 0
    assert prec == 0.0
    assert rec == 0.0
    assert f1 == 0.0

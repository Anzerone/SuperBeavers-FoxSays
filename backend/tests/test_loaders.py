"""Тесты loader-слоя под реальный корпус «Научный клубок».

Покрывают:
  * cp866-имена внутри zip;
  * рекурсивную распаковку вложенных архивов + идемпотентность;
  * склейку многотомников .001/.002 и определение типа;
  * разбор пути → doc_type / journal / year;
  * рекурсивный обход дерева с исключением служебных папок;
  * расширенный разбор числовых режимов (Gap #2);
  * извлечение текста из PPTX и XLSX.
"""

import io
import zipfile
from pathlib import Path

import pytest

from app.loaders import archives, documents
from app.loaders.structured import parse_mode_string


# --------------------------------------------------------------------------
# Имена cp866 внутри zip
# --------------------------------------------------------------------------

def test_decode_zip_name_cp866():
    original = "Источники информации/Доклад_Иванов.pdf"
    zi = zipfile.ZipInfo()
    # эмулируем архив без UTF-8-флага: cp866-байты, прочитанные как cp437
    zi.filename = original.encode("cp866").decode("cp437")
    zi.flag_bits = 0
    assert archives.decode_zip_name(zi) == original


def test_decode_zip_name_utf8_flag():
    zi = zipfile.ZipInfo()
    zi.filename = "Отчёт.pdf"
    zi.flag_bits = 0x800  # уже UTF-8
    assert archives.decode_zip_name(zi) == "Отчёт.pdf"


# --------------------------------------------------------------------------
# Разбор пути
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel, dtype, journal, year", [
    ("Источники информации/Доклады/Доклад_Иванов.pdf", "report", None, None),
    ("Источники информации/Журналы/Горный журнал/2025/ГЖ_01_25.pdf",
     "journal", "Горный журнал", 2025),
    ("Источники информации/Журналы/Горная промышленность/2024/ГП № 1-2024.pdf",
     "journal", "Горная промышленность", 2024),
    ("Источники информации/Статьи/some_article.pdf", "article", None, None),
    ("Источники информации/Обзоры/review.docx", "review", None, None),
    ("Источники информации/Материалы конференций/conf.pdf", "conference", None, None),
    ("random/unlabeled/file.txt", "document", None, None),
])
def test_classify_path(rel, dtype, journal, year, tmp_path):
    root = tmp_path
    p = root / rel
    meta = documents.classify_path(p, root=root)
    assert meta["doc_type"] == dtype
    assert meta["journal"] == journal
    assert meta["year"] == year


# --------------------------------------------------------------------------
# Рекурсивный обход
# --------------------------------------------------------------------------

def test_iter_document_paths_recursive_and_excludes(tmp_path):
    (tmp_path / "Доклады").mkdir()
    (tmp_path / "Доклады" / "a.pdf").write_bytes(b"%PDF-1.4 test")
    (tmp_path / "Журналы" / "ГЖ" / "2025").mkdir(parents=True)
    (tmp_path / "Журналы" / "ГЖ" / "2025" / "b.docx").write_bytes(b"PK")
    (tmp_path / "c.txt").write_text("hi", encoding="utf-8")
    # служебное — должно быть исключено
    (tmp_path / "dicts").mkdir()
    (tmp_path / "dicts" / "materials.csv").write_text("code", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    found = {p.name for p in documents.iter_document_paths(tmp_path)}
    assert found == {"a.pdf", "b.docx", "c.txt"}


# --------------------------------------------------------------------------
# Распаковка архивов
# --------------------------------------------------------------------------

def _make_zip(path: Path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_unpack_recursive_nested_and_idempotent(tmp_path):
    # inner.zip содержит документ
    inner_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_bytes, "w") as zf:
        zf.writestr("Статьи/deep.txt", "глубокий документ")
    # outer.zip содержит inner.zip
    outer = tmp_path / "outer.zip"
    _make_zip(outer, {"nested/inner.zip": inner_bytes.getvalue()})

    stats = archives.unpack_recursive(tmp_path)
    assert stats["archives"] >= 2  # outer + inner
    extracted = list(tmp_path.rglob("deep.txt"))
    assert extracted, "вложенный документ должен быть распакован"
    assert extracted[0].read_text(encoding="utf-8") == "глубокий документ"

    # повторный запуск ничего заново не распаковывает
    stats2 = archives.unpack_recursive(tmp_path)
    assert stats2["archives"] == 0
    assert stats2["skipped"] >= 1


def test_join_split_volumes_and_sniff(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("x.txt", "y")
    raw = payload.getvalue()
    mid = len(raw) // 2
    base = tmp_path / "archive"
    (base.with_suffix(".001")).write_bytes(raw[:mid])
    (base.with_suffix(".002")).write_bytes(raw[mid:])

    joined = archives.join_split_volumes(base.with_suffix(".001"), tmp_path / "work")
    assert joined is not None and joined.exists()
    assert archives._sniff(joined) == "zip"


# --------------------------------------------------------------------------
# Числовые режимы — Gap #2 (диапазоны кроме температуры)
# --------------------------------------------------------------------------

def test_parse_mode_string_numeric_ranges():
    p = parse_mode_string("отжиг 900 °C 1 ч")
    assert p["temperature_c"] == 900 and p["duration_h"] == 1

    assert parse_mode_string("концентрация H2SO4 300 г/л")["concentration_mgl"] == 300000
    assert parse_mode_string("выщелачивание при 1.5 МПа")["pressure_mpa"] == 1.5
    assert parse_mode_string("флотация pH 9.5")["ph_value"] == 9.5
    assert parse_mode_string("расход пульпы 12 м3/ч")["flow_rate_m3h"] == 12
    assert parse_mode_string("электролиз 250 А/м2")["current_density_am2"] == 250
    assert parse_mode_string("плотность тока 3 А/дм2")["current_density_am2"] == 300
    assert parse_mode_string("капзатраты 5 млн руб")["cost_rub"] == 5_000_000
    assert parse_mode_string("производительность 800 т/сут")["throughput_tday"] == 800


def test_parse_mode_string_temperature_range_avg():
    p = parse_mode_string("обжиг 1100-1200 °C")
    assert p["temperature_c"] == 1150


# --------------------------------------------------------------------------
# Извлечение текста из офисных форматов
# --------------------------------------------------------------------------

def test_extract_pptx(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    box = slide.shapes.add_textbox(0, 0, 5_000_000, 1_000_000)
    box.text_frame.text = "Флотация медно-никелевой руды при pH 9"
    out = tmp_path / "deck.pptx"
    prs.save(out)

    pages = documents.extract_text_pptx(out)
    assert pages and pages[0][0] == 1
    assert "Флотация" in pages[0][1]


def test_extract_excel(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Данные"
    ws.append(["Материал", "Прочность, МПа"])
    ws.append(["Сплав А1", 380])
    out = tmp_path / "table.xlsx"
    wb.save(out)

    pages = documents.extract_text_excel(out)
    assert pages
    text = pages[0][1]
    assert "Данные" in text and "Сплав А1" in text and "380" in text


def test_chunk_text_overlap():
    text = "слово " * 400  # ~2400 символов
    chunks = documents.chunk_text(text, size=800, overlap=200)
    assert len(chunks) >= 3
    assert all(len(c) <= 800 for c in chunks)

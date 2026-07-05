"""Loader for generated useful-info reports.

The report is produced by ``tools/extract_useful_info.py`` as JSONL:
one source file per line, with selected useful snippets.  This loader turns
those snippets into draft graph records so the ingestion pipeline can upsert
them as extracted experiments/conclusions linked to source documents.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DEFAULT_REPORT = Path("outputs/useful_info/useful_info_by_file.jsonl")

_INITIALS = r"[А-ЯЁ]\.\s*[А-ЯЁ]?\.?"
_AUTHOR_PATTERNS = [
    re.compile(rf"(?:докладчик|автор|исполнитель|подготовил[аи]?|научный сотрудник)\s*[:\-]?\s*([А-ЯЁ][А-ЯЁа-яё]+\s+{_INITIALS})"),
    re.compile(rf"\b([А-ЯЁ][а-яё]+\s+{_INITIALS})\b"),
]

_CONCLUSION_HINTS = (
    "вывод", "заключение", "показано", "установлено", "получено",
    "результат", "рекоменд", "привело", "эффективност",
    "conclusion", "result", "shown", "obtained", "recommended",
)


def _stable_id(prefix: str, seed: str, length: int = 12) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_doc_id(seed: str) -> str:
    return "DOC-" + hashlib.sha1(str(seed).encode("utf-8")).hexdigest()[:12].upper()


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _year_from_path(path: str) -> int | None:
    match = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", path or "")
    return int(match.group(0)) if match else None


def _title_from_path(path: str) -> str:
    return Path(path).stem or path


def _doc_id(corpus_dir: Path, rel_path: str) -> str:
    """Match document loader IDs when the original file is still present."""
    source_root = corpus_dir / "Источники информации"
    full = source_root / rel_path
    if full.exists():
        try:
            return _stable_doc_id(_file_hash(full))
        except Exception:  # noqa: BLE001
            pass
    return _stable_doc_id(f"useful-info:{rel_path}")


def _doc_type(rel_path: str) -> str:
    low = [part.lower() for part in Path("Источники информации", rel_path).parts]
    if "доклады" in low:
        return "report"
    if "журналы" in low:
        return "journal"
    if "статьи" in low:
        return "article"
    if "обзоры" in low:
        return "review"
    if "материалы конференций" in low:
        return "conference"
    return "document"


def _source_category(rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    return parts[0] if parts else None


def _extract_author_names(text: str, file_name: str) -> list[str]:
    candidates: list[str] = []
    haystack = f"{file_name} {text[:800]}"
    for pattern in _AUTHOR_PATTERNS:
        for match in pattern.finditer(haystack):
            name = re.sub(r"\s+(?=[А-ЯЁ]\.)", " ", _clean(match.group(1)))
            name = re.sub(r"\.\s+([А-ЯЁ]\.)", r".\1", name)
            name = re.sub(r"([А-ЯЁ]\.[А-ЯЁ])$", r"\1.", name)
            if 5 <= len(name) <= 80 and name not in candidates:
                candidates.append(name)
            if len(candidates) >= 3:
                return candidates
    return candidates


def _author_id(name: str) -> str:
    translit = re.sub(r"[^A-Za-zА-Яа-яЁё0-9]+", "-", name).strip("-").upper()
    if translit:
        return "AUTH-EXT-" + hashlib.sha1(name.lower().encode("utf-8")).hexdigest()[:10].upper()
    return _stable_id("AUTH-EXT", name, 10)


def _looks_like_conclusion(snippet: str) -> bool:
    low = snippet.lower()
    return any(hint in low for hint in _CONCLUSION_HINTS)


_CYR_RE = re.compile(r"[А-Яа-яЁё]")


def _is_mostly_russian(text):
    if not text:
        return False
    cyr = len(_CYR_RE.findall(text))
    return cyr / max(len(text), 1) >= 0.15


def _snippet_title(snippet, fallback):
    # Английские сниппеты не годятся как заголовок узла в русскоязычном UI —
    # показываем нейтральную заглушку, а сам текст остаётся в description
    # для LLM-обогащения на qwen2.5:3b.
    snippet_clean = _clean(snippet)
    if not _is_mostly_russian(snippet_clean):
        return f"[EN] {fallback}"
    sentence = re.split(r"(?<=[.!?])\s+", snippet_clean)[0]
    sentence = sentence[:140].strip(" .;:")
    return sentence or fallback


def iter_useful_info_records(report_path, corpus_dir):
    """Yield draft records from a useful-info JSONL report.

    Each yielded item contains:
    - ``document``: minimal Document payload;
    - ``authors``: staff-like rows for Author upsert;
    - ``experiments``: structured experiment rows compatible with IngestService.
    """
    report = Path(report_path)
    corpus = Path(corpus_dir)
    if not report.exists():
        return

    for line_no, line in enumerate(report.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        rel_path = str(raw.get("path") or "").strip()
        snippets = raw.get("useful_info") or []
        if not rel_path or not snippets:
            continue

        doc_id = _doc_id(corpus, rel_path)
        title = _title_from_path(rel_path)
        year = _year_from_path(rel_path)
        all_text = "\n".join(_clean(s) for s in snippets if str(s).strip())
        author_names = _extract_author_names(all_text, raw.get("file_name") or title)
        author_rows = [
            {"author_id": _author_id(name), "full_name": name, "team_id": None}
            for name in author_names
        ]

        document = {
            "doc_id": doc_id,
            "title": title,
            "file_path": str(corpus / "Источники информации" / rel_path),
            "language": None,
            "country_code": None,
            "geo_region": None,
            "kind": "file",
            "format": raw.get("extension"),
            "doc_type": _doc_type(rel_path),
            "source_category": _source_category(rel_path),
            "journal": None,
            "year": year,
            "page_count": raw.get("pages_or_sheets") or 0,
            "pages": [(1, all_text[:4000])],
        }

        experiments = []
        for idx, snippet in enumerate(snippets, 1):
            snippet = _clean(str(snippet))
            if not snippet:
                continue
            seed = f"{doc_id}|{idx}|{snippet[:500]}"
            exp_id = _stable_id("EXP-UI", seed)
            conclusion = snippet if _looks_like_conclusion(snippet) else None
            experiments.append(
                {
                    "experiment_id": exp_id,
                    "title": _snippet_title(snippet, f"{title}: фрагмент {idx}"),
                    "description": snippet[:4000],
                    "year": year,
                    "date": None,
                    "material_codes": [],
                    "mode_codes": [],
                    "equipment_codes": [],
                    "author_ids": [row["author_id"] for row in author_rows],
                    "team_id": None,
                    "document_id": doc_id,
                    "tag_codes": ["useful_info", f"source_{document['doc_type']}"],
                    "property_code": None,
                    "property_value": None,
                    "property_unit": None,
                    "conclusion_text": conclusion,
                    "source": "useful_info",
                    "confidence": 0.45,
                    "line_no": line_no,
                }
            )

        if experiments:
            yield {"document": document, "authors": author_rows, "experiments": experiments}

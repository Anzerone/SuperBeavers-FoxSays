import csv
import re
from pathlib import Path
from uuid import uuid4

from docx import Document as DocxDocument
from loguru import logger
from pypdf import PdfReader

from app.models import Experiment, IngestStatus
from app.services.query_parser import parse_query
from app.services.repository import repository


class IngestService:
    def __init__(self) -> None:
        self.status = IngestStatus(state="idle")

    def load(self, corpus_dir: Path, limit: int, reset: bool = False) -> IngestStatus:
        self.status = IngestStatus(state="running")
        if reset:
            repository.experiments.clear()

        files = [item for item in corpus_dir.rglob("*") if item.is_file()] if corpus_dir.exists() else []
        selected = files[:limit]
        experiments: list[Experiment] = []
        warnings: list[str] = []

        for index, path in enumerate(selected, start=1):
            self.status = IngestStatus(
                state="running",
                files_seen=index,
                documents_loaded=repository.documents_loaded,
                experiments_loaded=len(experiments),
                warnings=warnings[:20],
            )
            try:
                if path.suffix.lower() in {".csv", ".xlsx"}:
                    experiments.extend(self._extract_csv(path))
                    continue
                text = self._extract_text(path)
            except Exception as exc:
                warnings.append(f"{path.name}: {exc}")
                continue

            if not text.strip():
                continue

            intent = parse_query(f"{path.name} {text[:1500]}")
            material = intent.materials[0] if intent.materials else "не определено"
            process = intent.processes[0] if intent.processes else "не определено"
            prop = intent.properties[0] if intent.properties else "общий вывод"
            snippet = self._meaningful_snippet(text, path.stem)
            geography = self._classify_geography(path, text, intent.geography)
            experiments.append(
                Experiment(
                    id=f"DOC-{uuid4().hex[:8]}",
                    title=path.stem[:120],
                    material=material,
                    process=process,
                    condition=", ".join(intent.numeric_constraints + intent.conditions) or "условия извлечены из документа",
                    result=snippet or "документ загружен в корпус",
                    property=prop,
                    geography=geography,
                    year=None,
                    source=path.name,
                    confidence=0.62 if "не определено" in {material, process} else 0.72,
                )
            )

        repository.add_experiments(experiments)
        self.status = IngestStatus(
            state="done",
            files_seen=len(selected),
            documents_loaded=repository.documents_loaded,
            experiments_loaded=len(experiments),
            warnings=warnings[:20],
        )
        logger.info("Ingest completed: {}", self.status.model_dump())
        return self.status

    def _extract_csv(self, path: Path) -> list[Experiment]:
        loaded: list[Experiment] = []
        if path.suffix.lower() == ".xlsx":
            return self._extract_xlsx(path)

        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                title = row.get("title") or row.get("name") or path.stem
                material = row.get("material") or row.get("materials") or "не определено"
                process = row.get("process") or row.get("mode") or row.get("technology") or "не определено"
                condition = row.get("condition") or row.get("mode_params") or row.get("params") or "условия из таблицы"
                prop = row.get("property") or row.get("metric") or "общий вывод"
                result = row.get("result") or row.get("conclusion") or row.get("effect") or "строка каталога загружена"
                confidence_raw = row.get("confidence") or "0.75"
                year_raw = row.get("year") or ""
                loaded.append(
                    Experiment(
                        id=row.get("id") or row.get("experiment_id") or f"CSV-{uuid4().hex[:8]}",
                        title=title[:120],
                        material=material,
                        process=process,
                        condition=condition,
                        result=result,
                        property=prop,
                        value=row.get("value") or None,
                        geography=row.get("geography") or row.get("geo") or "unknown",
                        year=int(year_raw) if str(year_raw).isdigit() else None,
                        source=row.get("source") or path.name,
                        confidence=float(confidence_raw) if self._is_float(confidence_raw) else 0.75,
                    )
                )
        return loaded

    def _extract_xlsx(self, path: Path) -> list[Experiment]:
        import pandas as pd

        loaded: list[Experiment] = []
        dataframe = pd.read_excel(path).fillna("")
        for row in dataframe.to_dict(orient="records"):
            title = str(row.get("title") or row.get("name") or path.stem)
            material = str(row.get("material") or row.get("materials") or "не определено")
            process = str(row.get("process") or row.get("mode") or row.get("technology") or "не определено")
            condition = str(row.get("condition") or row.get("mode_params") or row.get("params") or "условия из таблицы")
            prop = str(row.get("property") or row.get("metric") or "общий вывод")
            result = str(row.get("result") or row.get("conclusion") or row.get("effect") or "строка каталога загружена")
            loaded.append(
                Experiment(
                    id=str(row.get("id") or row.get("experiment_id") or f"XLSX-{uuid4().hex[:8]}"),
                    title=title[:120],
                    material=material,
                    process=process,
                    condition=condition,
                    result=result,
                    property=prop,
                    value=str(row.get("value") or "") or None,
                    geography=str(row.get("geography") or row.get("geo") or "unknown"),
                    year=int(row["year"]) if str(row.get("year", "")).isdigit() else None,
                    source=str(row.get("source") or path.name),
                    confidence=float(row["confidence"]) if self._is_float(row.get("confidence")) else 0.75,
                )
            )
        return loaded

    def _is_float(self, value: object) -> bool:
        try:
            float(str(value))
            return True
        except ValueError:
            return False

    def _classify_geography(self, path: Path, text: str, parsed_geo: str | None) -> str:
        title_sample = f"{path.name} {text[:700]}".lower()
        sample = f"{path.name} {text}".lower()
        strong_foreign_scope = [
            "зарубеж", "мировая практика", "мировой опыт", "international practice",
            "foreign practice", "world practice", "cerro matoso",
        ]
        foreign_markers = [
            "world practice", "international practice", "foreign practice",
            "зарубеж", "мировой опыт", "мировая практика", "передовой мировой опыт",
            "canada", "australia", "finland", "sweden", "germany", "china", "usa",
            "чили", "канада", "австрали", "финлянди", "швец", "германи", "китай",
        ]
        ru_markers = [
            "росси", "рф", "санкт-петербург", "москва", "норильск", "красноярск",
            "мурманск", "кольская", "кгмк", "норникель", "гипроникель",
            "ооо ", "ао ", "пао ", "фгбу", "институт",
        ]
        has_strong_foreign_scope = any(marker in title_sample for marker in strong_foreign_scope)
        has_foreign = any(marker in sample for marker in foreign_markers)
        has_ru = any(marker in sample for marker in ru_markers)
        if has_strong_foreign_scope:
            return "world"
        if parsed_geo == "world" and has_foreign and not has_ru:
            return "world"
        if has_foreign and not has_ru:
            return "world"
        if has_ru:
            return "ru"
        if parsed_geo in {"ru", "world"}:
            return parsed_geo
        if re.search(r"[а-яё]", sample):
            return "ru"
        return "world"

    def _meaningful_snippet(self, text: str, fallback: str) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            return fallback[:240] or "документ загружен в корпус"
        sentences = re.split(r"(?<=[.!?])\s+|;|\n", normalized)
        bad_markers = (
            "утверждаю", "директор департамента", "список исполнителей", "оглавление",
            "содержание", "главный специалист", "issn", "www.", "ежемесячный",
            "научно-технический", "обзор ", "справка ", "тематическая информация",
        )
        useful_markers = (
            "извлеч", "выщелач", "очист", "концентрац", "сульфат", "никел",
            "медь", "электро", "закач", "раствор", "католит", "анолит", "осад",
            "температур", "ph", "мг/л", "г/л", "%", "процесс", "технолог",
            "оборудован", "эксперимент", "исследован", "получен", "показал",
        )

        candidates: list[tuple[int, str]] = []
        for sentence in sentences:
            cleaned = re.sub(r"_{3,}", "", sentence).strip(" .,:;—-")
            lower = cleaned.lower()
            if len(cleaned) < 45:
                continue
            if any(marker in lower for marker in bad_markers):
                continue
            score = sum(2 for marker in useful_markers if marker in lower)
            score += min(len(cleaned) // 120, 2)
            if re.search(r"\d+(?:[,.]\d+)?\s*(мг/л|г/л|%|°|с|c|мпа|mpa)", lower):
                score += 3
            candidates.append((score, cleaned))

        if not candidates:
            cleaned = re.sub(r"_{3,}", "", normalized)
            cleaned = re.sub(r"\b(УТВЕРЖДАЮ|Оглавление|Содержание)\b.*?(?=[А-ЯЁA-Z][а-яёa-z]{4,})", "", cleaned)
            return (cleaned.strip(" .,:;—-") or fallback)[:240]

        best = max(candidates, key=lambda item: item[0])[1]
        return best[:240].rstrip()

    def _extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:20000]
        if suffix == ".docx":
            doc = DocxDocument(path)
            return "\n".join(paragraph.text for paragraph in doc.paragraphs)[:20000]
        if suffix == ".pdf":
            reader = PdfReader(path)
            pages = []
            for page in reader.pages[:8]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)[:20000]
        return ""


ingest_service = IngestService()

from collections import Counter
from datetime import date
import re
from uuid import uuid4

from app.models import (
    AskResponse,
    EntityType,
    Evidence,
    Experiment,
    Fact,
    GapCell,
    GapsResponse,
    GraphEdge,
    GraphNode,
    QueryIntent,
    TimelinePoint,
)

try:
    from app.db.neo4j_client import graph_store
except Exception:
    graph_store = None


class KnowledgeRepository:
    def __init__(self) -> None:
        self.experiments: dict[str, Experiment] = {}
        self.documents_loaded = 0

    def add_experiments(self, experiments: list[Experiment]) -> None:
        for experiment in experiments:
            self.experiments[experiment.id] = experiment
        self.documents_loaded = len({item.source for item in self.experiments.values()})
        if graph_store:
            graph_store.upsert_experiments(experiments)

    def search(self, intent: QueryIntent, verified_only: bool = True) -> list[Experiment]:
        items = list(self.experiments.values())
        if verified_only:
            items = [item for item in items if item.confidence >= 0.6]
        items = self._filter_by_year(items, intent.time_range)
        items = self._filter_by_geography(items, intent.geography)

        def score(item: Experiment) -> float:
            joined = f"{item.material} {item.process} {item.property} {item.condition} {item.result}".lower()
            total = 0.0
            for group in [intent.materials, intent.processes, intent.properties, intent.conditions]:
                total += sum(2.0 for value in group if value.lower() in joined)
            total += self._semantic_score(intent, item)
            if intent.numeric_filters:
                total += sum(2.5 for flt in intent.numeric_filters if self._numeric_match(item, flt))
                if not any(self._numeric_match(item, flt) for flt in intent.numeric_filters):
                    total -= 1.5
            if intent.geography and intent.geography not in {"all", "world"} and item.geography == intent.geography:
                total += 0.8
            elif intent.geography == "world" and item.geography in {"world", "foreign"}:
                total += 0.5
            return total

        ranked = sorted(items, key=lambda item: (score(item), item.confidence, item.year or 0), reverse=True)
        return [item for item in ranked if score(item) > 0][:80]

    def ask(self, question: str, intent: QueryIntent, verified_only: bool = True) -> AskResponse:
        experiments = self.search(intent, verified_only=verified_only)
        graph_insights = self._graph_insights(intent, experiments)
        nodes, edges = self._graph_from_experiments(experiments, intent, graph_insights)
        facts = [
            Fact(
                topic=item.process,
                condition=item.condition,
                conclusion=self._result_summary(item),
                source=item.source,
                confidence=item.confidence,
            )
            for item in experiments[:8]
        ]
        evidence = [
            Evidence(
                source_id=item.id,
                title=item.source,
                page=None,
                snippet=self._result_summary(item),
                confidence=item.confidence,
                updated_at=date.today().isoformat(),
            )
            for item in experiments[:5]
        ]
        answer = self._synthesize(intent, experiments)
        return AskResponse(
            id=str(uuid4()),
            question=question,
            intent=intent,
            answer=answer,
            nodes=nodes,
            edges=edges,
            facts=facts,
            evidence=evidence,
            metrics={
                "sources": len({item.source for item in experiments}),
                "facts": len(facts),
                "confidence": round(sum(item.confidence for item in experiments) / max(len(experiments), 1), 2),
                "experiments": len(experiments),
                "gaps": len(graph_insights.get("gaps", [])),
                "contradictions": len(graph_insights.get("contradictions", [])),
            },
            graph_insights=graph_insights,
        )

    def experiment(self, experiment_id: str) -> Experiment | None:
        return self.experiments.get(experiment_id)

    def autocomplete(self, query: str, kind: str | None = None) -> list[str]:
        values: set[str] = set()
        for item in self.experiments.values():
            if kind in {None, "material"}:
                values.add(item.material)
            if kind in {None, "process", "mode"}:
                values.add(item.process)
            if kind in {None, "property"}:
                values.add(item.property)
            if kind in {None, "source", "document"}:
                values.add(item.source)
        q = query.lower()
        return sorted(value for value in values if q in value.lower())[:12]

    def gaps(self) -> GapsResponse:
        rows = sorted({item.material for item in self.experiments.values()})
        cols = sorted({item.process for item in self.experiments.values()})
        counts = Counter((item.material, item.process) for item in self.experiments.values())
        cells: list[GapCell] = []
        for row in rows:
            for col in cols:
                count = counts[(row, col)]
                if count == 0:
                    status = "gap"
                elif count < 2:
                    status = "weak"
                else:
                    status = "covered"
                cells.append(GapCell(row=row, col=col, count=count, status=status))
        return GapsResponse(rows=rows, cols=cols, cells=cells)

    def timeline(self, material: str | None = None, property_name: str | None = None) -> list[TimelinePoint]:
        items = list(self.experiments.values())
        if material:
            items = [item for item in items if material.lower() in item.material.lower()]
        if property_name:
            items = [item for item in items if property_name.lower() in item.property.lower()]
        points: list[TimelinePoint] = []
        for item in sorted(items, key=lambda value: value.year or 0):
            if item.year:
                numeric = 0.2 + item.confidence / 4
                points.append(TimelinePoint(year=item.year, value=round(numeric, 2), label=item.result[:54], source=item.source))
        return points

    def _filter_by_year(self, items: list[Experiment], time_range: str | None) -> list[Experiment]:
        if not time_range or time_range in {"all", "все", "все годы"}:
            return items
        digits = re.search(r"\d+", str(time_range))
        if not digits:
            return items
        years_back = int(digits.group(0))
        cutoff = date.today().year - years_back
        known = [item for item in items if item.year and item.year >= cutoff]
        return known or items

    def _filter_by_geography(self, items: list[Experiment], geography: str | None) -> list[Experiment]:
        if not geography or geography in {"all", "any"}:
            return items
        if geography == "world":
            filtered = [
                item for item in items
                if item.geography in {"world", "foreign"} and self._is_world_practice(item)
            ]
        elif geography == "ru":
            filtered = [item for item in items if item.geography in {"ru", "russia", "domestic"}]
        else:
            filtered = [item for item in items if item.geography == geography]
        return filtered

    def _is_world_practice(self, item: Experiment) -> bool:
        text = f"{item.title} {item.source} {item.result}".lower()
        explicit_foreign = (
            "зарубеж", "мировая практика", "мировой опыт", "foreign practice",
            "international practice", "world practice", "cerro matoso", "уэльва",
            "huelva", "minga", "benavente", "rabanal", "wisdom",
            "canada", "australia", "finland", "sweden", "germany", "china", "usa",
            "чили", "канада", "австрали", "финлянди", "швец", "германи", "китай",
        )
        domestic = (
            "росси", "рф", "оао", "пао", "ооо", "норникель", "гипроникель",
            "южуралникель", "норильск", "красноярск", "кольская", "мурманск",
            "санкт-петербург", "москва",
        )
        if any(marker in text for marker in domestic) and not any(marker in text for marker in explicit_foreign):
            return False
        return True

    def _semantic_score(self, intent: QueryIntent, item: Experiment) -> float:
        query_terms = set()
        for value in (
            intent.materials + intent.processes + intent.properties
            + intent.conditions + intent.numeric_constraints
        ):
            query_terms.update(self._terms(value))
        if not query_terms:
            return 0.0
        joined = f"{item.title} {item.material} {item.process} {item.property} {item.condition} {item.result} {item.source}"
        hay_terms = set(self._terms(joined))
        overlap = len(query_terms & hay_terms)
        return min(overlap * 0.45, 4.0)

    def _terms(self, text: str) -> list[str]:
        stop = {
            "для", "при", "что", "как", "или", "где", "найти", "какие", "способы",
            "решения", "практика", "вариант", "данные", "применялись", "применялись",
        }
        tokens = [
            token for token in re.split(r"[^0-9a-zа-яё]+", (text or "").lower())
            if len(token) >= 3 and token not in stop
        ]
        stems = [token[:6] for token in tokens if len(token) > 6]
        return tokens + stems

    def _numeric_match(self, item: Experiment, flt: dict[str, object]) -> bool:
        text = f"{item.condition} {item.result} {item.value or ''}".lower().replace(",", ".")
        expected_unit = str(flt.get("unit") or "").lower()
        values = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(мг/л|мг/дм3|мг/дм³|г/л|°c|°с|c|с|%|мпа|mpa|ph)?", text):
            unit = (match.group(2) or expected_unit).lower().replace("°с", "°c").replace("с", "c")
            value = float(match.group(1))
            if unit == "г/л":
                value *= 1000
                unit = "мг/л"
            if expected_unit and unit and unit != expected_unit:
                continue
            values.append(value)
        if not values:
            return False
        op = flt.get("operator")
        target = float(flt.get("value") or 0)
        lo = flt.get("min")
        hi = flt.get("max")
        for value in values:
            if op == "<" and value < target:
                return True
            if op == "<=" and value <= target:
                return True
            if op == ">" and value > target:
                return True
            if op == ">=" and value >= target:
                return True
            if op in {"=", "=="} and abs(value - target) < 1e-9:
                return True
            if op == "between" and lo is not None and hi is not None and float(lo) <= value <= float(hi):
                return True
        return False

    def _graph_insights(self, intent: QueryIntent, experiments: list[Experiment]) -> dict[str, object]:
        gaps = self._detect_gaps(intent, experiments)
        contradictions = self._detect_contradictions(experiments)
        experts = self._related_experts(experiments)
        facilities = self._related_facilities(experiments)
        comparisons = self._comparison_summary(intent, experiments)
        chains = [
            {
                "material": self._effective_material(item, intent),
                "process": self._effective_process(item, intent),
                "equipment": self._infer_equipment(item),
                "result": self._result_summary(item),
                "experiment_id": item.id,
            }
            for item in experiments[:8]
        ]
        return {
            "chains": chains,
            "gaps": gaps,
            "contradictions": contradictions,
            "experts": experts,
            "facilities": facilities,
            "comparisons": comparisons,
        }

    def _detect_gaps(self, intent: QueryIntent, experiments: list[Experiment]) -> list[dict[str, object]]:
        if experiments:
            return []
        combo = intent.conditions + intent.processes + intent.materials + intent.properties
        if not combo:
            return []
        return [{
            "combination": " + ".join(combo),
            "message": f"Нет экспериментов для комбинации: {' + '.join(combo)}",
            "severity": "gap",
        }]

    def _detect_contradictions(self, experiments: list[Experiment]) -> list[dict[str, object]]:
        groups: dict[tuple[str, str, str], list[Experiment]] = {}
        for item in experiments:
            key = (item.material.lower(), item.process.lower(), item.property.lower())
            groups.setdefault(key, []).append(item)
        contradictions = []
        positive = ("повыш", "увелич", "улучш", "эффектив", "снижает риск")
        negative = ("сниж", "ухудш", "рост риска", "неэффектив", "негатив")
        for key, rows in groups.items():
            has_pos = [r for r in rows if any(word in r.result.lower() for word in positive)]
            has_neg = [r for r in rows if any(word in r.result.lower() for word in negative)]
            if has_pos and has_neg:
                contradictions.append({
                    "topic": " / ".join(key),
                    "positive": has_pos[0].id,
                    "negative": has_neg[0].id,
                    "message": "Есть разнонаправленные выводы по одной связке материал-процесс-показатель.",
                })
        return contradictions[:5]

    def _related_experts(self, experiments: list[Experiment]) -> list[dict[str, str]]:
        experts: dict[str, dict[str, str]] = {}
        pattern = re.compile(r"([А-ЯЁ][а-яё]+)\s+([А-ЯЁ])\.?\s*([А-ЯЁ])?\.?")
        for item in experiments[:20]:
            for match in pattern.finditer(item.source):
                name = " ".join(part for part in match.groups() if part)
                experts[name] = {"name": name, "source": item.source}
        return list(experts.values())[:8]

    def _related_facilities(self, experiments: list[Experiment]) -> list[dict[str, str]]:
        aliases = {
            "ЛГМ": "Лаборатория геомеханики",
            "ЛПМ": "Лаборатория пирометаллургии",
            "ИАЦ": "Информационно-аналитический центр",
            "Гипроникель": "Институт Гипроникель",
            "КГМК": "Кольская ГМК",
        }
        found: dict[str, dict[str, str]] = {}
        for item in experiments[:30]:
            text = f"{item.title} {item.source} {item.result}"
            for code, name in aliases.items():
                if code.lower() in text.lower():
                    found[code] = {"code": code, "name": name, "source": item.source}
        return list(found.values())[:8]

    def _comparison_summary(self, intent: QueryIntent, experiments: list[Experiment]) -> list[dict[str, object]]:
        if not intent.comparisons:
            return []
        out = []
        for cmp in intent.comparisons:
            if cmp.get("kind") == "geography":
                ru = [item for item in experiments if item.geography in {"ru", "russia", "domestic"}]
                world = [item for item in experiments if item.geography in {"world", "foreign"}]
                out.append({
                    "left": cmp["left"],
                    "right": cmp["right"],
                    "left_count": len(ru),
                    "right_count": len(world),
                    "left_sources": len({item.source for item in ru}),
                    "right_sources": len({item.source for item in world}),
                })
            else:
                left_terms = set(self._terms(cmp.get("left", "")))
                right_terms = set(self._terms(cmp.get("right", "")))
                left = [item for item in experiments if left_terms & set(self._terms(f"{item.material} {item.process} {item.result}"))]
                right = [item for item in experiments if right_terms & set(self._terms(f"{item.material} {item.process} {item.result}"))]
                out.append({
                    "left": cmp.get("left"),
                    "right": cmp.get("right"),
                    "left_count": len(left),
                    "right_count": len(right),
                })
        return out

    def _infer_equipment(self, item: Experiment) -> str:
        text = f"{item.condition} {item.result} {item.title} {item.source}".lower()
        patterns = [
            (r"печ", "печь"),
            (r"реактор|автоклав", "реактор"),
            (r"насос|скважин|закач", "скважина/насосная система"),
            (r"электролиз|ячейк|ванн", "электролизная ячейка"),
            (r"сепаратор", "сепаратор"),
            (r"флотомаш|флотац", "флотационная машина"),
        ]
        for pattern, label in patterns:
            if re.search(pattern, text):
                return label
        return "оборудование не указано"

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text or "").strip()
        text = re.sub(r"_{3,}", "", text)
        text = re.sub(r"\bISSN\s+\S+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"www\.\S+", "", text, flags=re.IGNORECASE)
        boilerplate = [
            "УТВЕРЖДАЮ", "Директор Департамента", "Список исполнителей",
            "Оглавление", "ЕЖЕМЕСЯЧНЫЙ НАУЧНО-ТЕХНИЧЕСКИЙ",
        ]
        for marker in boilerplate:
            text = text.replace(marker, "")
        return text.strip(" .,:;—-")

    def _source_title(self, item: Experiment) -> str:
        title = (item.title or item.source or "").strip()
        if title and title not in {"не определено", "общий вывод"}:
            return title
        return item.source

    def _result_summary(self, item: Experiment) -> str:
        text = self._clean_text(item.result)
        if not text:
            return f"Источник содержит сведения по теме: {self._source_title(item)}."
        sentences = re.split(r"(?<=[.!?])\s+", text)
        useful = []
        bad_prefixes = (
            "обзор", "справка", "тематическая информация", "уважаемые", "в номере",
            "главный специалист", "содержание", "исполнитель",
        )
        bad_markers = (
            "утверждаю", "директор департамента", "список исполнителей",
            "оглавление", "issn", "www.", "ежемесячный",
        )
        for sentence in sentences:
            s = sentence.strip()
            if len(s) < 32:
                continue
            if s.lower().startswith(bad_prefixes):
                continue
            if any(marker in s.lower() for marker in bad_markers):
                continue
            useful.append(s)
            if len(useful) >= 2:
                break
        summary = " ".join(useful) or text
        if len(summary) > 260:
            summary = summary[:257].rstrip() + "..."
        return summary

    def _effective_material(self, item: Experiment, intent: QueryIntent | None) -> str:
        if item.material and item.material != "не определено":
            return item.material
        if intent and intent.materials:
            return intent.materials[0]
        return item.material or "не определено"

    def _effective_process(self, item: Experiment, intent: QueryIntent | None) -> str:
        if item.process and item.process != "не определено":
            return item.process
        if intent and intent.processes:
            return intent.processes[0]
        return item.process or "не определено"

    def _graph_from_experiments(
        self,
        experiments: list[Experiment],
        intent: QueryIntent | None = None,
        insights: dict[str, object] | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_map: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        def add_node(key: str, label: str, kind: EntityType, confidence: float = 0.8, metadata: dict | None = None) -> None:
            node_map.setdefault(key, GraphNode(id=key, label=label, type=kind, confidence=confidence, metadata=metadata or {}))

        for item in experiments[:10]:
            exp_id = f"experiment:{item.id}"
            material_label = self._effective_material(item, intent)
            process_label = self._effective_process(item, intent)
            material_id = f"material:{material_label}"
            process_id = f"process:{process_label}"
            equipment = self._infer_equipment(item)
            equipment_id = f"equipment:{equipment}"
            property_id = f"property:{item.property}"
            document_id = f"document:{item.source}"
            conclusion_id = f"conclusion:{item.id}"

            add_node(exp_id, item.id, EntityType.experiment, item.confidence, {"year": item.year, "geography": item.geography})
            add_node(material_id, material_label, EntityType.material, item.confidence)
            add_node(process_id, process_label, EntityType.process, item.confidence)
            add_node(equipment_id, equipment, EntityType.equipment, item.confidence)
            add_node(property_id, item.property, EntityType.property, item.confidence)
            add_node(document_id, item.source, EntityType.document, item.confidence)
            result_summary = self._result_summary(item)
            add_node(conclusion_id, result_summary[:70], EntityType.conclusion, item.confidence, {"full_text": result_summary})

            edges.extend(
                [
                    GraphEdge(id=f"{item.id}:material", source=exp_id, target=material_id, type="USED_MATERIAL", label="материал", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:process", source=exp_id, target=process_id, type="USED_PROCESS", label="процесс", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:chain:m:p", source=material_id, target=process_id, type="CHAIN_MATERIAL_PROCESS", label="материал → процесс", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:equipment", source=process_id, target=equipment_id, type="USES_EQUIPMENT", label="оборудование", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:chain:e:r", source=equipment_id, target=conclusion_id, type="EQUIPMENT_RESULT", label="оборудование → результат", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:property", source=exp_id, target=property_id, type="MEASURED", label="показатель", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:document", source=exp_id, target=document_id, type="DOCUMENTED_IN", label="источник", confidence=item.confidence),
                    GraphEdge(id=f"{item.id}:conclusion", source=exp_id, target=conclusion_id, type="RESULTED_IN", label="вывод", confidence=item.confidence),
                ]
            )
            for expert in self._related_experts([item])[:2]:
                expert_id = f"expert:{expert['name']}"
                add_node(expert_id, expert["name"], EntityType.expert, item.confidence, {"source": item.source})
                edges.append(GraphEdge(id=f"{item.id}:expert:{expert['name']}", source=expert_id, target=document_id, type="AUTHORED_OR_MENTIONED", label="эксперт", confidence=item.confidence))
            for facility in self._related_facilities([item])[:2]:
                facility_id = f"facility:{facility['code']}"
                add_node(facility_id, facility["name"], EntityType.facility, item.confidence, facility)
                edges.append(GraphEdge(id=f"{item.id}:facility:{facility['code']}", source=facility_id, target=exp_id, type="RELATED_FACILITY", label="лаборатория", confidence=item.confidence))

        insights = insights or {}
        for idx, gap in enumerate(insights.get("gaps", [])):
            gap_id = f"gap:{idx}"
            add_node(gap_id, gap["message"], EntityType.tag, 0.95, {"status": "gap", **gap})
            for value in (intent.materials + intent.processes + intent.conditions if intent else [])[:4]:
                target = f"query:{value}"
                add_node(target, value, EntityType.tag, 0.7, {"status": "query_term"})
                edges.append(GraphEdge(id=f"{gap_id}:{target}", source=target, target=gap_id, type="MISSING_COMBINATION", label="пробел", confidence=0.95))
        for idx, contradiction in enumerate(insights.get("contradictions", [])):
            left = f"conclusion:{contradiction['positive']}"
            right = f"conclusion:{contradiction['negative']}"
            edges.append(GraphEdge(id=f"contradiction:{idx}", source=left, target=right, type="CONTRADICTS", label="противоречие", confidence=0.9, metadata=contradiction))
        return list(node_map.values()), edges

    def _synthesize(self, intent: QueryIntent, experiments: list[Experiment]) -> str:
        if not experiments:
            combo = " + ".join(intent.conditions + intent.processes + intent.materials)
            if combo:
                return f"По запросу не найдено подтвержденных экспериментов. Пробел: нет экспериментов для комбинации {combo}."
            return "По запросу не найдено подтвержденных фактов. Рекомендуется расширить фильтры или добавить документы в корпус."
        count = len(experiments)
        sources = len({item.source for item in experiments})
        scope = ", ".join(intent.processes or intent.materials or ["выбранной теме"])
        top_sources = list(dict.fromkeys(self._source_title(item) for item in experiments[:5]))
        materials = [m for m, _ in Counter(self._effective_material(item, intent) for item in experiments).most_common(3) if m and m != "не определено"]
        processes = [p for p, _ in Counter(self._effective_process(item, intent) for item in experiments).most_common(3) if p and p != "не определено"]
        geography_note = ""
        if intent.geography == "world":
            geography_note = " Фильтр «мировая практика» исключает записи, распознанные как российские или неопределённые по географии."
        elif intent.geography == "ru":
            geography_note = " Показаны записи, распознанные как российская практика."
        base = (
            f"По теме «{scope}» найдено {count} релевантных записей из {sources} источников. "
            f"Основные материалы: {', '.join(materials) if materials else 'не выделены автоматически'}. "
            f"Основные процессы: {', '.join(processes) if processes else 'не выделены автоматически'}. "
            f"Ключевые источники: {', '.join(top_sources[:3])}."
            f"{geography_note} Для детального вывода проверьте таблицу фактов и граф связей: там видно, какой источник поддерживает каждую связку."
        )
        if intent.numeric_filters:
            nums = "; ".join(flt["raw"] for flt in intent.numeric_filters)
            base += f" Учтены числовые условия: {nums}."
        if intent.comparisons:
            base += " Запрос распознан как сравнительный: результаты сгруппированы в метаданных графа."
        return base


repository = KnowledgeRepository()

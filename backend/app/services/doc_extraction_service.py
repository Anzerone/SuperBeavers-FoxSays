"""DocExtractionService — фаза 2 ингеста: извлечение структуры из документов.

Реальный корпус приходит как сырые PDF/DOCX/PPTX/XLS без готовой таблицы
экспериментов. Этот сервис проходит по уже загруженным документам и их чанкам
и достраивает граф:

  1. NER (материалы/режимы/свойства) → рёбра :MENTIONS к справочникам;
  2. LLM-экстрактор экспериментов → узлы :Experiment / :Conclusion с провенансом
     (source_doc_id, extracted=true, confidence) и связями
     USED_MATERIAL / USED_MODE / MEASURED / RESULTED_IN / DOCUMENTED_IN;
  3. числовые параметры режима разбираются parse_mode_string (температура,
     концентрация, давление, pH, расход, плотность тока, экономика, throughput).

Проход опциональный и «мягкий»: без Ollama (llm_enabled=false или недоступен)
LLM-шаг тихо пропускается, остаётся словарный NER по чанкам. Ничего не падает.
Спорные (confidence < extract_min_confidence) записи не пишутся в граф —
они отправляются в события для human-review.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from loguru import logger

from app.config import settings
from app.db.neo4j_client import get_neo4j
from app.loaders import structured as struct_loader
from app.prompts import experiment_extractor as ee_prompts
from app.services import dictionary
from app.services.llm_service import LLMService
from app.services.ner_service import NERService
from app.services.rag_service import RAGService


def _prov_code(prefix, text):
    h = hashlib.sha1(str(text).strip().lower().encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-EXT-{h}"


# Признаки того, что сниппет — оглавление курса / список модулей, а не эксперимент.
# Достаточно двух совпадений, чтобы дропнуть без LLM-звонка.
_TOC_MARKERS = (
    "модул", "раздел", "глав", "оглавлен", "содержани курса",
    "о курсе", "введение видеолек", "видеолекция", "тестировани",
    "презентац", "слайд", "лекц", "план курса", "структура курс",
    "литератур", "контрольн", "домашн", "самопровер",
    "компонент модул", "элемент модул",
)

# Экспериментальный «якорь»: слова из химтех/металлургии, реально описывающие
# процесс или измерение. Хотя бы одно должно быть, иначе — не эксперимент.
_EXP_MARKERS = (
    "температур", "давлен", "концентрац", "выщелачив", "плавк", "содержан",
    "извлечен", "прочност", "растворен", "окислен", "восстановлен",
    "фильтрац", "флотац", "электролиз", "коррозион", "твёрдост", "твердост",
    "вязкост", "плотност", "проводим", "pH", "мг/л", "МПа", "об.%", "мас.%",
    "мкм", "ppm", "°c", "°с",
)

# Регулярка «число + единица» — самый надёжный маркер измерения.
_NUM_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:%|°[cCсС]|мг/л|г/л|мкм|нм|мм|см|м|мл|л|МПа|МПа|мбар|кПа|Па|"
    r"ppm|мас\.?%|об\.?%|А/м²|А/м2|мкА|кА|мВт|Вт|кВт|Дж|кДж|мВ|В|кВ|Ом|"
    r"кг|т|тонн|ч|мин|сут)",
    re.IGNORECASE,
)


def _looks_experimental(text):
    """Быстрый эвристический фильтр «это описание эксперимента, а не TOC»."""
    if not text or len(text) < 40:
        return False
    low = text.lower()
    toc_hits = sum(1 for m in _TOC_MARKERS if m in low)
    if toc_hits >= 2:
        return False
    exp_hits = sum(1 for m in _EXP_MARKERS if m.lower() in low)
    has_num_unit = bool(_NUM_UNIT_RE.search(text))
    return has_num_unit or exp_hits >= 1


def _first_dict_hit(index_dict, entities, text):
    """Ищет самое длинное совпадение любого ключа словаря в тексте.
    Возвращает display_name entity (для последующего resolve_or_register)
    или None. Работает как поверхностный NER — не идеально, но быстро
    и без второго LLM-вызова."""
    if not text or not index_dict:
        return None
    from app.services.dictionary import _norm as _dict_norm
    low = _dict_norm(text)
    if not low:
        return None
    best_len = 0
    best_code = None
    for key, code in index_dict.items():
        if not key or len(key) < 3:
            continue
        if key in low and len(key) > best_len:
            best_len = len(key)
            best_code = code
    if not best_code:
        return None
    ent = entities.get(best_code) or {}
    return ent.get("display_name") or best_code


class DocExtractionService:
    def __init__(self, llm: LLMService, rag: RAGService, ner: NERService):
        self.llm = llm
        self.rag = rag
        self.ner = ner
        self.events: list[dict[str, Any]] = []
        self.stats = {
            "documents": 0, "mentions": 0, "experiments": 0,
            "conclusions": 0, "review_pending": 0, "skipped_llm": 0,
        }

    def _emit(self, event_type, payload):
        self.events.append({"type": event_type, **payload})

    # ------------------------------------------------------------------
    # Публичный вход
    # ------------------------------------------------------------------

    async def extract_all(self, limit=None, scope="all", should_cancel=None):
        limit = limit or settings.extract_max_docs
        docs = self._list_documents(limit=limit, scope=scope)
        cancelled = False
        for doc in docs:
            if should_cancel and should_cancel():
                cancelled = True
                self._emit("cancelled", {"processed": self.stats["documents"]})
                logger.info(f"Doc extraction cancelled after {self.stats['documents']} docs")
                break
            try:
                await self.extract_document(doc["doc_id"])
                self.stats["documents"] += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"extract failed for {doc['doc_id']}: {e}")
                self._emit("extract_error", {"doc_id": doc["doc_id"], "error": str(e)[:200]})
        if not cancelled:
            logger.info(f"Doc extraction done: {self.stats}")
        return {"stats": self.stats, "events": self.events, "cancelled": cancelled}

    async def extract_document(self, doc_id):
        chunks = self._doc_chunks(doc_id, limit=settings.extract_max_chunks_per_doc)
        if not chunks:
            return

        # --- 1. NER → MENTIONS (дёшево, работает и без LLM через fallback) ---
        mentioned = await self._ner_mentions(doc_id, chunks)
        self.stats["mentions"] += mentioned

        # --- 2. LLM-экстрактор экспериментов (мягко, если LLM доступна) ---
        if settings.llm_enabled:
            for ch in chunks:
                await self._extract_experiments_from_chunk(doc_id, ch)
        else:
            self.stats["skipped_llm"] += 1

        # помечаем документ как пройденный (для scope='new')
        neo = get_neo4j()
        with neo.driver.session() as s:
            s.execute_write(_tx_mark_extracted, doc_id)

    # ------------------------------------------------------------------
    # NER → MENTIONS
    # ------------------------------------------------------------------

    async def _ner_mentions(self, doc_id, chunks):
        from collections import defaultdict
        found = defaultdict(set)
        for ch in chunks:
            try:
                r = await self.ner.extract(ch["text"])
            except Exception:  # noqa: BLE001 — LLM недоступна → словарный fallback
                r = self._dict_ner(ch["text"])
            for kind in ("materials", "modes", "properties"):
                for it in r.get(kind, []):
                    if it.get("match"):
                        found[kind].add(it["match"])

        neo = get_neo4j()
        added = 0
        with neo.driver.session() as s:
            for kind, label in (("materials", "Material"),
                                ("modes", "Mode"), ("properties", "Property")):
                for code in found[kind]:
                    s.execute_write(_tx_mention, doc_id, label, code, 0.9)
                    added += 1
        if added:
            self._emit("mentions_added", {"doc_id": doc_id, "count": added})
        return added

    def _dict_ner(self, text):
        """Словарный NER без LLM: точный + fuzzy матчинг по справочникам."""
        low = (text or "").lower()
        out = {"materials": [], "modes": [], "properties": []}
        for kind, items, lookup in (
            ("materials", dictionary.all_materials(), dictionary.lookup_material),
            ("modes", dictionary.all_modes(), dictionary.lookup_mode),
            ("properties", dictionary.all_properties(), dictionary.lookup_property),
        ):
            for ent in items:
                for key in [ent["display_name"]] + (ent.get("aliases") or []):
                    if key and key.lower() in low:
                        out[kind].append({"raw": key, "match": ent["code"]})
                        break
        return out

    # ------------------------------------------------------------------
    # LLM-экстрактор экспериментов
    # ------------------------------------------------------------------

    async def _extract_experiments_from_chunk(self, doc_id, chunk):
        mats = [m["code"] for m in dictionary.all_materials()[:40]]
        props = [p["code"] for p in dictionary.all_properties()[:30]]
        prompt = ee_prompts.build_prompt(chunk["text"], known_materials=mats,
                                         known_properties=props)
        try:
            # Экстракция идёт на tool-модели (qwen2.5:3b) — она мельче, не выселяет
            # 14b synth из VRAM и не блокирует Q&A. Задача структурная (материал/
            # режим/свойство/значение), 3b с ней справляется.
            result = await self.llm.generate_json(
                prompt, system=ee_prompts.SYSTEM,
                model=(settings.ollama_model_extract or None), max_tokens=600,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"LLM extract unavailable: {e}")
            self.stats["skipped_llm"] += 1
            return
        if not result:
            return

        for rec in (result.get("experiments") or []):
            conf = float(rec.get("confidence") or 0.0)
            if conf < settings.extract_min_confidence:
                self.stats["review_pending"] += 1
                self._emit("review_pending", {"doc_id": doc_id, "record": rec, "confidence": conf})
                continue
            self._upsert_extracted_experiment(doc_id, chunk, rec, conf)

    # ------------------------------------------------------------------
    # Обогащение useful_info экспериментов (Шаг 2)
    # ------------------------------------------------------------------

    async def enrich_useful_info_experiments(self, limit=None, should_cancel=None):
        """Прогоняет черновые useful_info-эксперименты через OLLAMA_MODEL_ENRICH и
        достраивает USED_MATERIAL / USED_MODE / MEASURED / RESULTED_IN.

        Черновые записи создаёт IngestService._import_useful_info: у них
        source='useful_info', description = сниппет, но нет связей с
        материалом/режимом/свойством. LLM превращает сниппет в структуру.
        """
        rows = self._list_useful_info_experiments(limit)
        if not rows:
            logger.info("useful_info enrich: nothing to do")
            return {"stats": self.stats, "events": self.events}

        logger.info(f"useful_info enrich: {len(rows)} experiments queued")
        import asyncio
        from app.services.llm_service import user_request_gate
        cancelled = False
        processed = 0
        for row in rows:
            if should_cancel and should_cancel():
                cancelled = True
                self._emit("cancelled", {"processed": processed})
                logger.info(f"useful_info enrich cancelled after {processed} rows")
                break
            # Пауза между итерациями + уступка user-запросам: если UI сейчас
            # ждёт ответ от /ask или /gaps/hypothesis, enrichment замирает.
            # Иначе enrich-модель + интерактивная synth-модель на одном GPU
            # конкурируют и гипотеза не приходит по 2 минуты.
            await user_request_gate.wait_until_free()
            try:
                await self._enrich_one_useful_info(row)
                processed += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"enrich failed for {row['exp_id']}: {e}")
                self._emit("enrich_error", {"exp_id": row["exp_id"], "error": str(e)[:200]})
            await asyncio.sleep(0.1)
        if not cancelled:
            logger.info(f"useful_info enrich done: {self.stats}")
        return {"stats": self.stats, "events": self.events, "cancelled": cancelled}

    def _list_useful_info_experiments(self, limit):
        neo = get_neo4j()
        # Берём только те, где ещё нет структурных связей — чтобы не пересчитывать
        # то же самое при повторном вызове. Description < 60 симв. — не тратим
        # LLM на такие короткие фрагменты, там нечего структурировать.
        # Плюс серверный prefilter: отсекаем сниппеты без чисел и без ключевых
        # экспериментальных слов — это оглавления учебных курсов, LLM возвращает
        # на них {"experiments": []} после ~7 секунд, а их 90%+ в корпусе.
        q = """
        MATCH (e:Experiment)
        WHERE e.source = 'useful_info'
          AND size(coalesce(e.description, '')) >= 60
          AND NOT (e)-[:USED_MATERIAL]->()
          AND NOT (e)-[:USED_MODE]->()
          AND NOT (e)-[:MEASURED]->()
        OPTIONAL MATCH (e)-[:DOCUMENTED_IN]->(d:Document)
        RETURN e.experiment_id AS exp_id,
               e.description   AS description,
               e.title         AS title,
               d.doc_id        AS doc_id
        LIMIT $lim
        """
        # По дефолту — без потолка (25k, что заведомо больше корпуса). Ручной
        # limit можно передать через POST /useful_info/enrich body.
        lim = int(limit) if limit else 25000
        with neo.driver.session() as s:
            recs = s.run(q, lim=lim)
            rows = [dict(r) for r in recs]

        # Prefilter garbage перед тем как отправить на LLM. Раньше 95% времени
        # съедали снипеты вида «5] 5 Компоненты модуля | 5 блоков 12 модулей…»
        # (оглавления курса) — они дают {"experiments": []} после ~7 сек LLM.
        kept, dropped = [], 0
        for r in rows:
            if _looks_experimental(r.get("description") or ""):
                kept.append(r)
            else:
                dropped += 1
        if dropped:
            logger.info(f"useful_info prefilter: kept {len(kept)}, dropped {dropped} as non-experimental")
        return kept

    async def _enrich_one_useful_info(self, row):
        text = (row.get("description") or "").strip()
        if len(text) < 40:
            return

        # Pattern-matching до LLM: если в сниппете явно есть ≥2 из
        # {material, mode, property} по словарю — минуем LLM (~30 сек экономии).
        prefilter = dictionary.pattern_prefilter(text)
        if prefilter:
            self._apply_structure_to_experiment(row, prefilter, float(prefilter["confidence"]))
            self._emit("useful_info_prefilter", {
                "exp_id": row["exp_id"],
                "confidence": prefilter["confidence"],
            })
            return

        mats = [m["code"] for m in dictionary.all_materials()[:40]]
        props = [p["code"] for p in dictionary.all_properties()[:30]]
        prompt = ee_prompts.build_prompt(text, known_materials=mats, known_properties=props)
        try:
            result = await self.llm.generate_json(
                prompt, system=ee_prompts.SYSTEM,
                model=(settings.ollama_model_enrich or settings.ollama_model_extract or None),
                max_tokens=settings.useful_info_enrich_max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"LLM enrich unavailable: {e}")
            self.stats["skipped_llm"] += 1
            return
        if not result:
            return

        applied = 0
        for rec in (result.get("experiments") or []):
            conf = float(rec.get("confidence") or 0.0)
            if conf < settings.extract_min_confidence:
                self.stats["review_pending"] += 1
                self._emit("review_pending", {
                    "exp_id": row["exp_id"], "record": rec, "confidence": conf,
                })
                continue
            self._apply_structure_to_experiment(row, rec, conf)
            applied += 1
        if applied:
            self._emit("useful_info_enriched", {
                "exp_id": row["exp_id"], "records_applied": applied,
            })

    def _apply_structure_to_experiment(self, row, rec, conf):
        """Достраивает связи существующему Experiment (не создаёт новый)."""
        exp_id = row["exp_id"]
        doc_id = row.get("doc_id")
        material = (rec.get("material") or "").strip()
        mode = (rec.get("mode") or "").strip()
        prop = (rec.get("property") or "").strip()
        conclusion = (rec.get("conclusion") or "").strip()
        if not (material or mode or prop or conclusion):
            return

        # Fallback на словарный NER, если LLM не вернул material/mode/property.
        # На корпусе Норникеля LLM оставлял material="" в 84% случаев — сниппет
        # описывает измерение, но конкретный материал только подразумевается
        # (из контекста документа). Дешевле пробежаться по description +
        # title + doc-title регуляркой словаря, чем гонять ещё один LLM-вызов.
        haystack = " ".join([
            (row.get("description") or ""),
            (row.get("title") or ""),
        ])
        if not material:
            hit = _first_dict_hit(dictionary._material_index,
                                  dictionary._materials, haystack)
            if hit:
                material = hit
        if not mode:
            hit = _first_dict_hit(dictionary._mode_index,
                                  dictionary._modes, haystack)
            if hit:
                mode = hit
        if not prop:
            hit = _first_dict_hit(dictionary._property_index,
                                  dictionary._properties, haystack)
            if hit:
                prop = hit

        mat_code = self._resolve_or_register(material, "material") if material else None
        prop_code = self._resolve_or_register(prop, "property") if prop else None
        mode_code = self._resolve_or_register(mode, "mode") if mode else None

        value = rec.get("value")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        unit = rec.get("unit")
        parsed_mode = struct_loader.parse_mode_string(mode) if mode else None

        neo = get_neo4j()
        with neo.driver.session() as s:
            # обновляем confidence, если LLM оценил выше
            s.execute_write(_tx_bump_confidence, exp_id, conf)
            if mat_code:
                s.execute_write(_tx_used, exp_id, "Material", mat_code, "USED_MATERIAL")
            if mode_code:
                s.execute_write(_tx_used, exp_id, "Mode", mode_code, "USED_MODE")
                self._attach_mode_params(s, mode_code, parsed_mode)
            if prop_code:
                s.execute_write(_tx_measured, exp_id, prop_code, value, unit)
            if conclusion:
                conc_id = "CONC-EXT-" + hashlib.sha1(
                    (exp_id + conclusion).encode("utf-8")).hexdigest()[:12].upper()
                s.execute_write(_tx_conclusion, conc_id, conclusion, conf, doc_id or "")
                s.execute_write(_tx_resulted_in, exp_id, conc_id)
                self.stats["conclusions"] += 1

        self.stats["experiments"] += 1

    def _upsert_extracted_experiment(self, doc_id, chunk, rec, conf):
        material = (rec.get("material") or "").strip()
        mode = (rec.get("mode") or "").strip()
        prop = (rec.get("property") or "").strip()
        conclusion = (rec.get("conclusion") or "").strip()
        if not (material or mode or prop):
            return

        mat_code = self._resolve_or_register(material, "material") if material else None
        prop_code = self._resolve_or_register(prop, "property") if prop else None
        mode_code = self._resolve_or_register(mode, "mode") if mode else None

        exp_seed = f"{doc_id}|{material}|{mode}|{prop}|{chunk.get('page')}"
        exp_id = "EXP-EXT-" + hashlib.sha1(exp_seed.encode("utf-8")).hexdigest()[:12].upper()

        value = rec.get("value")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        unit = rec.get("unit")

        parsed_mode = struct_loader.parse_mode_string(mode) if mode else None

        neo = get_neo4j()
        with neo.driver.session() as s:
            s.execute_write(_tx_extracted_experiment, exp_id, rec, doc_id, conf, chunk.get("page"))
            s.execute_write(_tx_doc_link, exp_id, doc_id)
            if mat_code:
                s.execute_write(_tx_used, exp_id, "Material", mat_code, "USED_MATERIAL")
            if mode_code:
                s.execute_write(_tx_used, exp_id, "Mode", mode_code, "USED_MODE")
                self._attach_mode_params(s, mode_code, parsed_mode)
            if prop_code:
                s.execute_write(_tx_measured, exp_id, prop_code, value, unit)
            if conclusion:
                conc_id = "CONC-EXT-" + hashlib.sha1(
                    (exp_id + conclusion).encode("utf-8")).hexdigest()[:12].upper()
                s.execute_write(_tx_conclusion, conc_id, conclusion, conf, doc_id)
                s.execute_write(_tx_resulted_in, exp_id, conc_id)
                self.stats["conclusions"] += 1

        self.stats["experiments"] += 1
        self._emit("experiment_extracted", {
            "doc_id": doc_id, "experiment_id": exp_id,
            "material": mat_code, "mode": mode_code, "property": prop_code,
            "value": value, "confidence": conf,
        })

    def _attach_mode_params(self, session, mode_code, parsed):
        if not parsed:
            return
        for name, unit in (
            ("temperature_c", "°C"), ("duration_h", "h"), ("pressure_mpa", "MPa"),
            ("concentration_mgl", "mg/l"), ("flow_rate_m3h", "m^3/h"),
            ("ph_value", "pH"), ("current_density_am2", "A/m^2"),
            ("cost_rub", "RUB"), ("throughput_tday", "t/day"),
        ):
            if name in parsed:
                pname = name.rsplit("_", 1)[0]
                session.execute_write(_tx_mode_param, mode_code, pname, float(parsed[name]), unit)

    def _resolve_or_register(self, text, kind):
        """Возвращает код известной сущности + гарантирует, что узел в графе
        существует и имеет display_name/description из словаря.

        Раньше при попадании в словарь (например LLM вернул «медный концентрат»
        → нашли MAT-CU-CONC) функция ретёрнилась сразу, не создавая узел.
        А `_tx_used` использует MATCH — если узла нет, ребро молча не создаётся.
        Итог: канонические материалы существовали только в памяти словаря,
        в Neo4j оставались лишь провизорные MAT-EXT-*.
        """
        lookup = {
            "material": dictionary.lookup_material,
            "property": dictionary.lookup_property,
            "mode": dictionary.lookup_mode,
        }[kind]
        get_entity = {
            "material": dictionary.get_material,
            "property": dictionary.get_property,
            "mode": dictionary.get_mode,
        }[kind]
        neo = get_neo4j()
        label = {"material": "Material", "property": "Property", "mode": "Mode"}[kind]

        code = lookup(text)
        if code:
            # Каноничный код — берём display_name и description из словаря
            ent = get_entity(code) or {}
            meta = ent.get("meta") or {}
            with neo.driver.session() as s:
                s.execute_write(_tx_upsert_dict_node, label, code,
                                ent.get("display_name") or text,
                                meta.get("description"))
            return code

        # Провизорный: LLM нашёл что-то, чего нет в словаре
        if kind == "material":
            code = _prov_code("MAT", text)
            dictionary.register_material(code, text, meta={"provenance": "extracted"})
        elif kind == "property":
            code = _prov_code("PROP", text)
            dictionary.register_property(code, text, meta={"provenance": "extracted"})
        else:
            code = _prov_code("MODE", text)
            dictionary.register_mode(code, text, meta={"provenance": "extracted"})
        with neo.driver.session() as s:
            s.execute_write(_tx_provisional_node, label, code, text)
        return code

    # ------------------------------------------------------------------
    # Доступ к данным
    # ------------------------------------------------------------------

    def _list_documents(self, limit, scope):
        neo = get_neo4j()
        where = ""
        if scope == "new":
            # ещё не проходили извлечение
            where = "WHERE d.extracted_at IS NULL"
        with neo.driver.session() as s:
            recs = s.run(
                f"MATCH (d:Document) {where} "
                "RETURN d.doc_id AS doc_id, d.title AS title, d.doc_type AS doc_type "
                "ORDER BY d.year DESC LIMIT $lim",
                lim=limit,
            )
            return [dict(r) for r in recs]

    def _doc_chunks(self, doc_id, limit):
        """Читает чанки документа из Qdrant по payload.doc_id."""
        try:
            from app.db.qdrant_client import get_qdrant
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        except Exception:  # noqa: BLE001
            return []
        flt = Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
        try:
            points, _ = get_qdrant().scroll(
                collection_name=settings.qdrant_collection_chunks,
                scroll_filter=flt, limit=limit, with_payload=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"qdrant scroll failed for {doc_id}: {e}")
            return []
        return [
            {"text": (p.payload or {}).get("text", ""), "page": (p.payload or {}).get("page")}
            for p in points if (p.payload or {}).get("text")
        ]


# ======================================================================
# Cypher tx
# ======================================================================

def _tx_mark_extracted(tx, doc_id):
    tx.run("MATCH (d:Document {doc_id: $did}) SET d.extracted_at = datetime()", did=doc_id)


def _tx_mention(tx, doc_id, label, code, conf):
    tx.run(
        f"""MATCH (d:Document {{doc_id: $did}}), (t:{label} {{code: $code}})
            MERGE (d)-[r:MENTIONS]->(t) SET r.confidence = $conf""",
        did=doc_id, code=code, conf=conf,
    )


def _tx_provisional_node(tx, label, code, name):
    tx.run(
        f"""MERGE (x:{label} {{code: $code}})
            ON CREATE SET x.display_name = $name, x.provenance = 'extracted'""",
        code=code, name=name[:200],
    )


def _tx_upsert_dict_node(tx, label, code, display_name, description):
    """Гарантирует узел канонической сущности со словарным display_name и
    полным description (если задан в CSV). На SET — не затираем description,
    если он уже прописан вручную, но обновляем display_name из словаря."""
    tx.run(
        f"""MERGE (x:{label} {{code: $code}})
            SET x.display_name = $name,
                x.provenance = coalesce(x.provenance, 'dictionary'),
                x.description = coalesce(x.description, $descr)""",
        code=code,
        name=(display_name or code)[:200],
        descr=(description or None) and str(description)[:2000],
    )


def _tx_bump_confidence(tx, exp_id, new_conf):
    tx.run(
        """MATCH (e:Experiment {experiment_id: $eid})
           SET e.confidence = CASE
                WHEN e.confidence IS NULL OR $c > e.confidence THEN $c
                ELSE e.confidence END,
               e.enriched_at = datetime()""",
        eid=exp_id, c=float(new_conf),
    )


def _tx_extracted_experiment(tx, exp_id, rec, doc_id, conf, page):
    tx.run(
        """MERGE (e:Experiment {experiment_id: $id})
           SET e.title = $title, e.description = $descr, e.extracted = true,
               e.source_doc_id = $doc, e.source_page = $page,
               e.confidence = $conf, e.extracted_at = datetime()""",
        id=exp_id,
        title=(rec.get("conclusion") or rec.get("material") or exp_id)[:200],
        descr=" ".join(str(rec.get(k) or "") for k in ("material", "mode", "property"))[:500],
        doc=doc_id, page=page, conf=conf,
    )


def _tx_doc_link(tx, exp_id, doc_id):
    tx.run(
        """MATCH (e:Experiment {experiment_id: $eid}), (d:Document {doc_id: $did})
           MERGE (e)-[r:DOCUMENTED_IN]->(d) SET r.weight = 1.0""",
        eid=exp_id, did=doc_id,
    )


def _tx_used(tx, exp_id, label, code, rel):
    tx.run(
        f"""MATCH (e:Experiment {{experiment_id: $eid}}), (t:{label} {{code: $code}})
            MERGE (e)-[r:{rel}]->(t) SET r.weight = 0.5, r.source = 'extracted'""",
        eid=exp_id, code=code,
    )


def _tx_measured(tx, exp_id, prop_code, value, unit):
    tx.run(
        """MATCH (e:Experiment {experiment_id: $eid}), (p:Property {code: $code})
           MERGE (e)-[r:MEASURED]->(p)
           SET r.value = $value, r.unit = $unit, r.weight = 0.5, r.source = 'extracted'""",
        eid=exp_id, code=prop_code, value=value, unit=unit,
    )


def _tx_mode_param(tx, mode_code, name, value, unit):
    tx.run(
        """MATCH (m:Mode {code: $mcode})
           MERGE (p:ModeParam {name: $name, unit: $unit, value: $value})
           MERGE (m)-[:HAS_PARAM]->(p)""",
        mcode=mode_code, name=name, unit=unit, value=value,
    )


def _tx_conclusion(tx, conc_id, text, conf, doc_id):
    tx.run(
        """MERGE (c:Conclusion {conclusion_id: $id})
           SET c.text = $text, c.confidence = $conf, c.extracted = true,
               c.source_doc_id = $doc, c.last_updated = datetime(),
               c.version = coalesce(c.version, 1)""",
        id=conc_id, text=text[:2000], conf=conf, doc=doc_id,
    )


def _tx_resulted_in(tx, exp_id, conc_id):
    tx.run(
        """MATCH (e:Experiment {experiment_id: $eid}), (c:Conclusion {conclusion_id: $cid})
           MERGE (e)-[r:RESULTED_IN]->(c) SET r.weight = 0.4""",
        eid=exp_id, cid=conc_id,
    )

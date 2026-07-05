"""ExportService: экспорт ответа Q&A в Markdown / JSON-LD / PDF."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger


class ExportService:

    def to_markdown(self, answer):
        """Форматирует полный ответ Q&A в Markdown."""
        q = answer.get("question", "")
        text = answer.get("answer", "")
        intent = answer.get("intent") or {}
        experiments = answer.get("experiments") or []
        sources = answer.get("sources") or []
        geo = answer.get("geo_filter") or "any"

        lines = [
            f"# Ответ: {q}",
            "",
            f"**Дата:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
            f"**Гео-фильтр:** {geo}  ",
            f"**Найдено экспериментов:** {len(experiments)}  ",
            "",
            "## Ответ",
            "",
            text or "_нет ответа_",
            "",
            "## Эксперименты",
            "",
            "| Название | Год | Материалы | Режим | Свойство | Значение | Гео | Документ |",
            "|----------|-----|-----------|-------|----------|----------|-----|----------|",
        ]
        geo_ru = {"domestic": "РФ/СНГ", "foreign": "зарубеж", "other": "н/д"}
        # Показываем только эксперименты со структурной связкой; черновики
        # useful_info без materials/modes/value — это шум, ID `EXP-UI-*` бесполезен.
        filtered = [
            e for e in experiments
            if (e.get("materials") or []) or (e.get("modes") or [])
            or e.get("property") or e.get("value") is not None
        ]
        for e in filtered[:30]:
            title = (e.get("title") or e.get("experiment_id") or "—").strip()
            title = title[:60].replace("|", "\\|") + ("…" if len(title) > 60 else "")
            val = e.get("value")
            val_str = f"{val} {e.get('unit') or ''}".strip() if val not in (None, "") else "—"
            lines.append(
                f"| {title} | {e.get('year') or '—'} | "
                f"{', '.join((e.get('materials') or [])[:2]) or '—'} | "
                f"{', '.join((e.get('modes') or [])[:2]) or '—'} | "
                f"{e.get('property') or '—'} | "
                f"{val_str} | "
                f"{geo_ru.get(e.get('geo_region'), 'н/д')} | {e.get('doc_id') or '—'} |"
            )
        if len(filtered) < len(experiments):
            lines.append("")
            lines.append(
                f"_Показано {len(filtered)} из {len(experiments)} экспериментов — только со "
                f"структурной связкой. Остальные — черновики useful_info без обогащения._"
            )
        lines.extend(["", "## Источники", ""])
        for i, s in enumerate(sources, 1):
            snippet = (s.get("text") or "").strip().replace("\n", " ")[:400]
            lines.append(f"**[Doc#{i}]** `{s.get('doc_id','?')}` стр. {s.get('page','?')}  ")
            lines.append(f"> {snippet}")
            lines.append("")
        if intent:
            lines.extend([
                "## Распознанные сущности",
                "",
                "```json",
                _safe_json_dumps(intent),
                "```",
            ])
        lines.append("")
        lines.append("---")
        lines.append("_Сгенерировано «Научный клубок» — Норникель AI Science Hack 2026._")
        return "\n".join(lines)

    def to_jsonld(self, answer):
        """JSON-LD в схеме schema.org/QAPage + ScholarlyArticle citations."""
        q = answer.get("question", "")
        text = answer.get("answer", "")
        experiments = answer.get("experiments") or []
        sources = answer.get("sources") or []

        ctx = {
            "@context": {
                "@vocab": "https://schema.org/",
                "nkl": "https://nornickel.ai/scientific-tangle/vocab#",
                "hasPart": "hasPart",
            },
            "@type": "QAPage",
            "mainEntity": {
                "@type": "Question",
                "text": q,
                "dateCreated": datetime.now(timezone.utc).isoformat(),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": text,
                    "author": {"@type": "SoftwareApplication", "name": "Научный клубок"},
                },
            },
            "nkl:experiments": [
                {
                    "@type": "Dataset",
                    "identifier": e.get("experiment_id"),
                    "name": e.get("title"),
                    "temporalCoverage": str(e.get("year") or ""),
                    "nkl:materials": e.get("materials") or [],
                    "nkl:modes": e.get("modes") or [],
                    "nkl:property": e.get("property"),
                    "nkl:value": e.get("value"),
                    "nkl:unit": e.get("unit"),
                    "nkl:geo_region": e.get("geo_region"),
                    "nkl:country_code": e.get("country_code"),
                    "citation": e.get("doc_id"),
                    "confidence": e.get("confidence"),
                }
                for e in experiments[:50]
            ],
            "citation": [
                {
                    "@type": "CreativeWork",
                    "identifier": s.get("doc_id"),
                    "position": i + 1,
                    "pagination": str(s.get("page") or ""),
                    "text": (s.get("text") or "")[:800],
                }
                for i, s in enumerate(sources)
            ],
            "license": "https://opensource.org/licenses/MIT",
        }
        return ctx

    def to_pdf_stream(self, answer):
        """Простой PDF через reportlab. Возвращает bytes."""
        try:
            from io import BytesIO
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            )
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError:
            logger.warning("reportlab not installed")
            return None

        # Регистрируем DejaVu Sans — Helvetica по дефолту не рендерит кириллицу
        # (получались чёрные квадраты в MD/PDF-выгрузке). DejaVu лежит в базовом
        # Debian-образе backend'а под /usr/share/fonts/truetype/dejavu.
        _register_cyrillic_font()

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        # Переопределяем шрифт всем базовым стилям — иначе Paragraph продолжит
        # брать Helvetica через parent-цепочку.
        for name in ("Normal", "BodyText", "Italic", "Heading1", "Heading2"):
            if name in styles.byName:
                s = styles[name]
                s.fontName = "DejaVuSans-Bold" if name.startswith("Heading") else "DejaVuSans"
        h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=colors.HexColor("#0B2545"),
                            fontName="DejaVuSans-Bold")
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#1D57A6"),
                            fontName="DejaVuSans-Bold")
        story = []

        story.append(Paragraph("Научный клубок", h1))
        story.append(Paragraph("Норникель AI Science Hack 2026", styles["Normal"]))
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph(f"<b>Вопрос:</b> {answer.get('question','')}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Дата:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                               styles["BodyText"]))
        story.append(Paragraph(f"<b>Гео-фильтр:</b> {answer.get('geo_filter','any')}", styles["BodyText"]))
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("Ответ", h2))
        for para in (answer.get("answer") or "").split("\n"):
            if para.strip():
                story.append(Paragraph(para, styles["BodyText"]))
                story.append(Spacer(1, 0.15*cm))

        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Эксперименты", h2))
        experiments = answer.get("experiments") or []

        def _has_signal(e):
            """Строка полезна только если есть хоть одна структурная связка.
            Черновики useful_info без materials/modes/property — шум для читателя:
            их ID `EXP-UI-*` смыслом не обладают, а название — обрывок первого
            предложения сниппета."""
            return bool(
                (e.get("materials") or []) or (e.get("modes") or [])
                or e.get("property") or e.get("value") is not None
            )

        rows = [e for e in experiments if _has_signal(e)][:15]
        if rows:
            geo_ru = {"domestic": "РФ/СНГ", "foreign": "зарубеж", "other": "н/д"}
            tbl_data = [["Название", "Год", "Материалы", "Свойство", "Значение", "Гео"]]
            for e in rows:
                title = (e.get("title") or e.get("experiment_id") or "—").strip()
                # Убираем «дурные» заголовки-сниппеты: если начинается со
                # служебных фраз или очень длинный — обрезаем аккуратно.
                title_short = title[:55] + ("…" if len(title) > 55 else "")
                val = e.get("value")
                val_str = f"{val} {e.get('unit') or ''}".strip() if val not in (None, "") else "—"
                tbl_data.append([
                    title_short,
                    str(e.get("year") or "—"),
                    ", ".join((e.get("materials") or [])[:2])[:30] or "—",
                    (e.get("property") or "—")[:20],
                    val_str,
                    geo_ru.get(e.get("geo_region"), "н/д"),
                ])
            tbl = Table(tbl_data, hAlign="LEFT",
                        colWidths=[6.5*cm, 1.2*cm, 3*cm, 3*cm, 2*cm, 1.5*cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0B2545")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "DejaVuSans-Bold"),
                ("FONTNAME", (0,1), (-1,-1), "DejaVuSans"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,0), 6),
                ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#E1E5EB")),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
            ]))
            story.append(tbl)
            if len(rows) < len(experiments):
                story.append(Spacer(1, 0.15*cm))
                story.append(Paragraph(
                    f"<i>Из {len(experiments)} найденных экспериментов показаны {len(rows)} "
                    f"со структурной связкой (материал / режим / свойство). "
                    f"Остальные — черновики useful_info без обогащения.</i>",
                    styles["Italic"]))
        else:
            story.append(Paragraph(
                "<i>Структурированных экспериментов не найдено — ответ строился на текстовых чанках-источниках "
                "(см. раздел ниже). Черновики useful_info без обогащения материалами/режимами скрыты.</i>",
                styles["Italic"]))

        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Источники", h2))
        for i, s in enumerate(answer.get("sources") or [], 1):
            story.append(Paragraph(
                f"<b>[Doc#{i}]</b> {s.get('doc_id','?')} стр. {s.get('page','?')}<br/>"
                f"<i>{(s.get('text') or '')[:300]}...</i>",
                styles["BodyText"]))
            story.append(Spacer(1, 0.15*cm))

        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(
            "<i>Сгенерировано «Научный клубок».</i>",
            styles["Italic"]))
        doc.build(story)
        buf.seek(0)
        return buf.read()


def _safe_json_dumps(obj):
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


_FONT_REGISTERED = False


def _register_cyrillic_font():
    """Ленивая регистрация DejaVu Sans (regular + bold) для reportlab.
    Идемпотентно — второй вызов no-op. Fallback пути на случай другого дистрибутива."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from pathlib import Path
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf",
         "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ]
    for reg, bold in candidates:
        if Path(reg).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont("DejaVuSans", reg))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold))
            _FONT_REGISTERED = True
            logger.info(f"PDF font registered: {reg}")
            return
    logger.warning("DejaVu Sans not found — PDF export will show squares for Cyrillic")

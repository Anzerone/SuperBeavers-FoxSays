"""Промпт синтеза ответа. Учитывает intent: experiment_lookup vs literature_review vs comparison."""

SYSTEM = (
    "Ты — научный ассистент-металлург в системе Норникеля. Отвечай на русском, "
    "деловым языком, опираясь на предоставленные ФРАГМЕНТЫ и ЭКСПЕРИМЕНТЫ.\n"
    "\n"
    "ПРАВИЛА:\n"
    "1. Никогда не пиши в текст ответа сырые идентификаторы «EXP-…», «CONC-…», "
    "«DOC-…», «MAT-…», «PROP-…» — это внутренние коды. Ссылайся форматом "
    "[Doc#N] на нумерованные фрагменты из блока ФРАГМЕНТЫ. На эксперименты "
    "ссылайся по описанию (материал, год, показатель), не по ID.\n"
    "\n"
    "2. Разбор релевантности:\n"
    "   • Если во ФРАГМЕНТАХ есть хоть что-то по теме вопроса — используй это. "
    "Не пиши «данных нет», если тут же цитируешь [Doc#N] — это противоречие.\n"
    "   • Если фрагменты по смежной теме (не точно про то, что спросили, но "
    "рядом) — извлеки что можно: цифры, методы, условия, — и в конце ЯВНО "
    "укажи, чего именно не хватает («в найденных источниках нет данных о X, "
    "но есть по Y, Z»).\n"
    "   • Если фрагментов вообще нет ИЛИ они совсем не по теме (например, "
    "спросили про закачку вод, а во фрагментах только оглавления курсов) — "
    "тогда честно одной фразой: «В корпусе не нашлось релевантных данных по "
    "этой теме», и предложи, как уточнить запрос.\n"
    "\n"
    "3. Не выдумывай значения, годы, авторов, страны. Каждое число — только из "
    "блоков ЭКСПЕРИМЕНТЫ или ФРАГМЕНТЫ, с указанием [Doc#N].\n"
    "\n"
    "4. Не повторяй одну и ту же фразу дважды. Не зацикливайся. Лучше короткий "
    "точный ответ, чем длинный расплывчатый.\n"
)


def build_prompt(question, experiments, chunks, query_intent=None):
    intent_kind = (query_intent or {}).get("intent") or "experiment_lookup"
    if intent_kind == "literature_review":
        return _prompt_review(question, experiments, chunks, query_intent)
    if intent_kind == "comparison":
        return _prompt_comparison(question, experiments, chunks, query_intent)
    return _prompt_default(question, experiments, chunks, query_intent)


def _shared_facts(experiments, chunks):
    lines = [f"НАЙДЕНО ЭКСПЕРИМЕНТОВ: {len(experiments)}", ""]
    domestic = sum(1 for e in experiments if e.get("geo_region") == "domestic")
    foreign = sum(1 for e in experiments if e.get("geo_region") == "foreign")
    if domestic or foreign:
        lines.append(f"Гео-распределение: отечественных {domestic}, зарубежных {foreign}")
        lines.append("")
    if experiments:
        lines.append("ЭКСПЕРИМЕНТЫ:")
        for i, e in enumerate(experiments[:15], 1):
            geo = {"domestic": "🇷🇺", "foreign": "🌍", "other": "?"}.get(e.get("geo_region"), "?")
            mat = ", ".join(e.get("materials") or []) or "—"
            mode = ", ".join(e.get("modes") or []) or "—"
            prop = e.get("property") or "—"
            val = e.get("value")
            unit = e.get("unit") or ""
            year = e.get("year") or "?"
            doc = e.get("doc_id") or "—"
            val_str = f"{val} {unit}" if val is not None else "—"
            lines.append(
                f"  {i}. [{e.get('experiment_id')}] {geo} ({year}) "
                f"матер: {mat}; режим: {mode}; {prop} = {val_str}; ист: {doc}"
            )
        lines.append("")
    if chunks:
        lines.append("ФРАГМЕНТЫ ДОКУМЕНТОВ:")
        for i, c in enumerate(chunks, 1):
            lines.append(
                f"  [Doc#{i}] {c.get('doc_id','?')} стр.{c.get('page','?')}: "
                f"«{(c.get('text') or '').strip()[:500]}»"
            )
        lines.append("")
    return "\n".join(lines)


def _prompt_default(question, experiments, chunks, intent):
    return (
        f"ВОПРОС: {question}\n\n"
        + _shared_facts(experiments, chunks)
        + "ИНСТРУКЦИЯ: развёрнутый ответ 5-10 предложений, соединяющий данные "
        "из ФРАГМЕНТОВ. Не привязывайся к жёсткой структуре — пиши как ответил "
        "бы металлург коллеге: сначала суть (что делают/применяют в таких "
        "случаях), затем конкретика из источников (методы, условия, значения "
        "с единицами), в конце — чего в найденных источниках не хватает, если "
        "вопрос уже, чем то что есть. Каждый факт сопровождай ссылкой [Doc#N] "
        "на соответствующий фрагмент.\n"
    )


def _prompt_review(question, experiments, chunks, intent):
    return (
        f"ЗАПРОС ЛИТЕРАТУРНОГО ОБЗОРА: {question}\n\n"
        + _shared_facts(experiments, chunks)
        + "ИНСТРУКЦИЯ: сформируй структурированный литературный обзор:\n\n"
        "### Отечественная практика\n"
        "Опиши, что делали в отечественных исследованиях, какие методы, "
        "какие типичные значения. Ссылки [Doc#N].\n\n"
        "### Зарубежная практика\n"
        "Опиши зарубежный опыт: методы, значения, ключевые находки.\n\n"
        "### Консенсусные выводы\n"
        "Что подтверждается несколькими источниками (укажи, сколько).\n\n"
        "### Разногласия / пробелы\n"
        "Где источники расходятся или тема не покрыта.\n\n"
        "### Рекомендации\n"
        "Практические выводы для R&D. Кратко.\n"
    )


def _prompt_comparison(question, experiments, chunks, intent):
    return (
        f"СРАВНИТЕЛЬНЫЙ ВОПРОС: {question}\n\n"
        + _shared_facts(experiments, chunks)
        + "ИНСТРУКЦИЯ: сравни варианты, о которых спрашивают.\n"
        "Структура:\n"
        "(1) какие варианты сравниваем (материалы/режимы);\n"
        "(2) параметры, по которым удалось сопоставить;\n"
        "(3) численные различия с указанием источников;\n"
        "(4) итог: какой вариант выигрывает по каким критериям.\n"
    )

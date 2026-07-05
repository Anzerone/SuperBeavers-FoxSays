"""Промпт LLM-NER: извлекает упоминания материалов/режимов/свойств из текста документа."""

SYSTEM = (
    "Ты — экстрактор сущностей в металлургических текстах. Из фрагмента документа "
    "вытащи упоминаемые материалы, режимы и свойства. Ответ — строгий JSON. "
    "Включай только то, что явно упомянуто."
)


def build_prompt(chunk_text, known_materials=None, known_properties=None):
    parts = [
        'Формат: {"materials": [...], "modes": [...], "properties": [...]}',
        "",
    ]
    if known_materials:
        parts.append("Если возможно, подгоняй к известным кодам материалов: "
                     + ", ".join(known_materials[:50]))
    if known_properties:
        parts.append("Известные свойства: " + ", ".join(known_properties[:30]))
    parts.append("")
    parts.append("ТЕКСТ:")
    parts.append(chunk_text[:1500])
    parts.append("")
    parts.append("JSON:")
    return "\n".join(parts)

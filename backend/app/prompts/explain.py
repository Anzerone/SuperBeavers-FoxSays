"""Промпты объяснения рёбер графа для эксплорера."""

SYSTEM = (
    "Ты — научный ассистент-металлург. Одним-двумя предложениями на русском "
    "объясни смысл связи между двумя узлами графа исследований. Опирайся "
    "только на представленные данные. Без вводных фраз."
)


def build_prompt(edge_type, src, dst, extra=None):
    extra = extra or {}
    src_name = src.get("title") or src.get("display_name") or src.get("id")
    dst_name = dst.get("title") or dst.get("display_name") or dst.get("id")
    src_type = src.get("type") or src.get("label")
    dst_type = dst.get("type") or dst.get("label")

    if edge_type == "USED_MATERIAL":
        return f"В эксперименте «{src_name}» использовали материал «{dst_name}». Кратко объясни, что это даёт для понимания эксперимента."
    if edge_type == "USED_MODE":
        return f"В эксперименте «{src_name}» применили режим «{dst_name}». Кратко объясни его суть и роль."
    if edge_type == "USED_EQUIPMENT":
        return f"Эксперимент «{src_name}» выполнен на установке «{dst_name}». Опиши коротко."
    if edge_type == "MEASURED":
        val = extra.get("value")
        unit = extra.get("unit") or ""
        return (
            f"В эксперименте «{src_name}» замерили свойство «{dst_name}»"
            f"{f' (значение {val} {unit})' if val is not None else ''}. "
            f"Что это значит — одна фраза."
        )
    if edge_type == "RESULTED_IN":
        return f"Эксперимент «{src_name}» привёл к выводу: «{dst_name}». Перескажи вывод проще."
    if edge_type == "SIMILAR_TO":
        score = extra.get("score")
        return (
            f"Два эксперимента похожи семантически{f' (cosine={score:.2f})' if score else ''}: "
            f"«{src_name}» и «{dst_name}». Что общего?"
        )
    if edge_type == "CONDUCTED_BY":
        return f"Эксперимент «{src_name}» провёл «{dst_name}». Одна фраза о связке."
    if edge_type == "DOCUMENTED_IN":
        return f"Эксперимент «{src_name}» описан в документе «{dst_name}». Одна фраза."
    return f"Связь типа {edge_type} между «{src_name}» ({src_type}) и «{dst_name}» ({dst_type}). Объясни одним предложением."

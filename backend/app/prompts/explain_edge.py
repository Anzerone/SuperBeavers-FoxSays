"""Промпты для генерации объяснений рёбер пути."""

SYSTEM = (
    "Ты — научный ассистент. Отвечаешь строго на русском, кратко, по делу, "
    "без вводных фраз. Опираешься только на предоставленные данные, не выдумываешь."
)


def explain_cites(a, b):
    return f"""Две статьи связаны цитированием: статья A ссылается на статью B.

СТАТЬЯ A:
Название: {a.get('title', '?')}
Год: {a.get('year', '?')}
Авторы: {_authors_str(a)}
Абстракт: {(a.get('abstract') or '')[:1200]}

СТАТЬЯ B (на неё ссылается A):
Название: {b.get('title', '?')}
Год: {b.get('year', '?')}
Авторы: {_authors_str(b)}
Абстракт: {(b.get('abstract') or '')[:1200]}

Объясни 2-4 предложениями: что A заимствует/развивает/опровергает из B, какая идея или метод связывает их. Если в абстракте B уже есть конкретная идея, на которую опирается A — назови её."""


def explain_coauthored(a, b):
    return f"""Два автора связаны соавторством.

АВТОР A: {a.get('title') or a.get('display_name', '?')}
АВТОР B: {b.get('title') or b.get('display_name', '?')}

Объясни одним предложением на русском: что значит эта связь для построения научного графа (общие работы → пересечение исследовательских интересов)."""


def explain_authored(author, work):
    return f"""Автор написал работу.

АВТОР: {author.get('title') or author.get('display_name', '?')}
РАБОТА: {work.get('title', '?')} ({work.get('year', '?')})
Абстракт: {(work.get('abstract') or '')[:800]}

Кратко (1-2 предложения): кто автор и о чём его работа."""


def explain_similar(a, b, score=None):
    score_str = f" (косинусное сходство {score:.2f})" if score else ""
    return f"""Две статьи тематически близки{score_str}.

СТАТЬЯ A:
Название: {a.get('title', '?')}
Абстракт: {(a.get('abstract') or '')[:1000]}

СТАТЬЯ B:
Название: {b.get('title', '?')}
Абстракт: {(b.get('abstract') or '')[:1000]}

Объясни 2-3 предложениями: какая конкретная тема, метод или объект исследования их сближает. Назови конкретику, а не общие слова."""


def explain_same_institution(a, b, inst_name=None):
    inst_str = f" — {inst_name}" if inst_name else ""
    return f"""Две статьи связаны через общую институцию авторов{inst_str}.

СТАТЬЯ A: {a.get('title', '?')} ({a.get('year', '?')})
СТАТЬЯ B: {b.get('title', '?')} ({b.get('year', '?')})

Одним предложением: что значит эта институциональная связь (общая школа/среда/возможные неявные пересечения)."""


def explain_affiliated_with(author, inst):
    return f"""Автор аффилирован с институцией.

АВТОР: {author.get('title') or author.get('display_name', '?')}
ИНСТИТУЦИЯ: {inst.get('title') or inst.get('display_name', '?')}

Одним предложением — что это даёт для понимания связей в графе."""


def explain_generic(rel_type, a, b):
    return f"""Связь типа {rel_type} между:
A: {a.get('title') or a.get('display_name', '?')}
B: {b.get('title') or b.get('display_name', '?')}

Одним предложением опиши смысл этой связи."""


def _authors_str(work):
    auths = work.get("authors")
    if not auths:
        return "?"
    if isinstance(auths, list):
        names = [a.get("display_name", "?") for a in auths[:3]]
        return ", ".join(names) + (" и др." if len(auths) > 3 else "")
    return str(auths)


def build_prompt(edge_type, src, dst, extra=None):
    extra = extra or {}
    if edge_type == "CITES":
        return explain_cites(src, dst)
    if edge_type == "COAUTHORED":
        return explain_coauthored(src, dst)
    if edge_type == "AUTHORED":
        # Может быть в любом направлении (Author->Work)
        if src.get("type") == "author" or "display_name" in src:
            return explain_authored(src, dst)
        return explain_authored(dst, src)
    if edge_type == "SIMILAR_TO":
        return explain_similar(src, dst, score=extra.get("score"))
    if edge_type == "SAME_INSTITUTION":
        return explain_same_institution(src, dst, inst_name=extra.get("inst_name"))
    if edge_type == "AFFILIATED_WITH":
        if src.get("type") == "author":
            return explain_affiliated_with(src, dst)
        return explain_affiliated_with(dst, src)
    return explain_generic(edge_type, src, dst)

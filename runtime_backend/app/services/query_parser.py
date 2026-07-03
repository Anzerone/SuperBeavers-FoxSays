import re

from app.models import QueryIntent


MATERIAL_PATTERNS = {
    "Ni-катоды": [r"ni[-\s]?катод", r"никелев.*катод"],
    "никель": [r"\bникел"],
    "никелевая руда": [r"никелев.*руд", r"ni[-\s]?руд"],
    "медно-никелевый штейн": [r"штейн"],
    "шахтная вода": [r"шахтн.*вод", r"рудничн.*вод", r"подземн.*вод", r"обессол"],
    "сульфаты": [r"сульфат"],
    "техногенный гипс": [r"гипс"],
    "Au, Ag, МПГ": [r"\bau\b", r"\bag\b", r"мпг", r"золото", r"серебр"],
}

PROCESS_PATTERNS = {
    "электроэкстракция": [r"электроэкстрак", r"католит", r"электролит"],
    "обессоливание": [r"обессол", r"сухой остаток"],
    "закачка вод": [r"закач", r"нагнетан", r"глубок.*горизонт", r"подземн.*горизонт"],
    "кучное выщелачивание": [r"кучн.*выщелач", r"выщелач"],
    "пирометаллургия": [r"пирометаллург", r"штейн", r"шлак", r"плав"],
    "очистка газов": [r"so2", r"so₂", r"газ"],
    "магнитная сепарация": [r"магнитн.*сепарац"],
    "грануляция": [r"грануляц"],
    "флотация": [r"флотац"],
}

PROPERTY_PATTERNS = {
    "скорость потока": [r"скорост.*поток", r"циркуляц"],
    "извлечение металла": [r"извлеч"],
    "концентрация сульфатов": [r"концентрац.*сульфат", r"сульфат.*(?:мг|г)\s*/\s*л"],
    "сухой остаток": [r"сухой остаток"],
    "распределение элементов": [r"распредел"],
    "экономические показатели": [r"капитальн", r"стоимост", r"эконом"],
}

NUMERIC_UNITS = r"мг/л|мг/дм3|мг/дм³|г/л|°c|°с|c|с|м/с|м3/ч|м³/ч|%|mpa|мпа|ph"
NUMERIC_RE = re.compile(
    rf"(?P<op><=|>=|<|>|≤|≥|=)?\s*"
    rf"(?P<lo>\d+(?:[,.]\d+)?)"
    rf"(?:\s*[–-]\s*(?P<hi>\d+(?:[,.]\d+)?))?\s*"
    rf"(?P<unit>{NUMERIC_UNITS})",
    re.IGNORECASE,
)

PARAMETER_HINTS = [
    (r"сульфат", "концентрация сульфатов"),
    (r"концентрац", "концентрация"),
    (r"температур|нагрев|охлажд", "температура"),
    (r"ph|pн", "pH"),
    (r"давлен", "давление"),
    (r"скорост|расход|поток|циркуляц", "скорость потока"),
    (r"извлеч", "извлечение"),
]


def _match(patterns: dict[str, list[str]], text: str) -> list[str]:
    found: list[str] = []
    for label, variants in patterns.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in variants):
            found.append(label)
    return found


def _parameter_near(text: str, start: int) -> str:
    window = text[max(0, start - 80):start]
    for pattern, label in PARAMETER_HINTS:
        if re.search(pattern, window, re.IGNORECASE):
            return label
    return "числовой параметр"


def _parse_numeric_filters(text: str) -> tuple[list[str], list[dict[str, object]]]:
    raw: list[str] = []
    filters: list[dict[str, object]] = []
    for match in NUMERIC_RE.finditer(text):
        op = match.group("op") or "="
        op = {"≤": "<=", "≥": ">="}.get(op, op)
        lo = float(match.group("lo").replace(",", "."))
        hi = match.group("hi")
        value = float(hi.replace(",", ".")) if hi else lo
        unit = match.group("unit").lower().replace("°с", "°c").replace("с", "c")
        if unit == "г/л":
            lo *= 1000
            value *= 1000
            unit = "мг/л"
        if hi:
            op = "between"
        raw.append(match.group(0).strip())
        filters.append({
            "parameter": _parameter_near(text, match.start()),
            "operator": op,
            "value": value,
            "min": lo if hi else None,
            "max": value if hi else None,
            "unit": unit,
            "raw": match.group(0).strip(),
        })
    return raw, filters


def _parse_comparisons(text: str) -> tuple[str | None, list[dict[str, str]]]:
    comparisons: list[dict[str, str]] = []
    geo = None
    domestic = any(word in text for word in ["отечествен", "росси", "рф", "снг"])
    world = any(word in text for word in ["миров", "зарубеж", "за рубеж", "иностран"])
    if domestic and world and any(word in text for word in [" vs ", "против", "сравн", " versus ", "или"]):
        comparisons.append({"left": "отечественная практика", "right": "мировая практика", "kind": "geography"})
        geo = "all"

    marker = re.search(r"(.+?)\s+(?:vs|versus|против)\s+(.+)", text, re.IGNORECASE)
    if marker and not comparisons:
        left = marker.group(1).strip(" ?.,;:")[-80:]
        right = marker.group(2).strip(" ?.,;:")[:80]
        comparisons.append({"left": left, "right": right, "kind": "variant"})

    return geo, comparisons


def parse_query(question: str, geography: str | None = None, years: str | None = None) -> QueryIntent:
    text = question.lower()
    numeric, numeric_filters = _parse_numeric_filters(text)
    comparison_geo, comparisons = _parse_comparisons(text)

    geo = geography or comparison_geo
    if not geo:
        if any(word in text for word in ["зарубеж", "миров", "за рубеж"]):
            geo = "world"
        elif "росси" in text or "отечествен" in text:
            geo = "ru"

    intent = QueryIntent(
        materials=_match(MATERIAL_PATTERNS, text),
        processes=_match(PROCESS_PATTERNS, text),
        properties=_match(PROPERTY_PATTERNS, text),
        numeric_constraints=[item.strip() for item in numeric],
        numeric_filters=numeric_filters,
        comparisons=comparisons,
        geography=geo,
        time_range=years,
    )

    if "холод" in text:
        intent.conditions.append("холодный климат")
    if "диафраг" in text:
        intent.conditions.append("диафрагменная ячейка")
    if "глубок" in text and "горизонт" in text:
        intent.conditions.append("глубокие горизонты")
    if "последние" in text and not intent.time_range:
        intent.time_range = "5"
    if "10 лет" in text and not intent.time_range:
        intent.time_range = "10"
    if "5 лет" in text and not intent.time_range:
        intent.time_range = "5"

    if comparisons:
        intent.intent = "comparison"
    elif "нет эксперимент" in text or "пробел" in text:
        intent.intent = "gap_analysis"

    return intent

"""Гео-классификация документов: РФ vs зарубеж."""

# ISO 3166-1 alpha-2 для «отечественная» практика (РФ + СНГ)
DOMESTIC_COUNTRIES = {"RU", "BY", "KZ", "KG", "AM", "AZ", "UZ", "TJ", "TM", "MD"}

# «Мировая практика»
FOREIGN_COUNTRIES = {
    "US", "CA", "GB", "DE", "FR", "IT", "ES", "NL", "SE", "NO", "FI", "PL",
    "CN", "JP", "KR", "IN", "AU", "BR", "AR", "MX", "ZA", "IL", "CH", "AT",
}


def classify_region(country_code):
    """Возвращает 'domestic' | 'foreign' | 'other'."""
    if not country_code:
        return "other"
    cc = country_code.upper()[:2]
    if cc in DOMESTIC_COUNTRIES:
        return "domestic"
    if cc in FOREIGN_COUNTRIES:
        return "foreign"
    return "other"


def region_label_ru(region):
    return {
        "domestic": "Отечественная практика",
        "foreign": "Зарубежная практика",
        "other": "Прочее",
    }.get(region, region)


def guess_country_from_text(text, language=None):
    """Эвристика для наполнения country_code при отсутствии в метаданных.

    Смотрим кириллицу (→ RU) или отдельные явные хинты в первых 500 символах.
    """
    if not text:
        return None
    sample = text[:500].lower()
    if language == "ru":
        return "RU"
    if language == "en":
        return "US"
    # эвристики по подписям/аффилиациям
    if any(k in sample for k in ["россия", "российск", "гмк", "норильск", "рф"]):
        return "RU"
    if any(k in sample for k in ["usa", "united states", "washington"]):
        return "US"
    if any(k in sample for k in ["china", "beijing", "shanghai"]):
        return "CN"
    if any(k in sample for k in ["germany", "berlin", "münchen"]):
        return "DE"
    # доля кириллицы > 30% → RU
    cyr = sum(1 for c in sample if "а" <= c <= "я")
    if cyr / max(len(sample), 1) > 0.3:
        return "RU"
    return None

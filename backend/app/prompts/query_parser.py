"""Промпт декомпозиции вопроса пользователя в QueryIntent JSON."""

SYSTEM = (
    "Ты — парсер вопросов учёного-металлурга. На вход — вопрос на русском. "
    "На выходе — строгий JSON, описывающий что искать в графе экспериментов. "
    "Никаких пояснений вне JSON. Если поле не определено — null или []. "
    "Если в вопросе явно несколько материалов/режимов/свойств — перечисли все. "
    "Если что-то двусмысленно — добавь уточняющий вопрос в open_questions.\n"
    "Никогда не копируй в JSON текст в угловых скобках из СХЕМЫ — это подсказки "
    "по типу поля, а не значение. В поле `raw` пиши подстроку прямо из вопроса; "
    "в поле `match` — код из «Известные коды …» либо null, если не подошёл ни один."
)

SCHEMA = """{
  "intent": "experiment_lookup" | "history" | "comparison" | "literature_review" | "explore",
  "materials": [{"raw": "...", "match": null}],
  "modes": [
    {"name": "<краткое имя процесса, напр. отжиг>",
     "params": [{"name": "temperature|duration|pressure|current_density",
                  "min": <число или null>, "max": <число или null>,
                  "value": <число или null>, "unit": "<°C|h|MPa|A/m^2>"}]}
  ],
  "properties": [{"raw": "...", "match": null}],
  "equipment": [{"raw": "...", "match": null}],
  "authors": [],
  "teams": [],
  "time_range": {"from": <год>, "to": <год>} | null,
  "tags": [],
  "open_questions": ["..."]
}"""

EXAMPLES = [
    {
        "q": "что делали по сплаву ХН77ТЮР при отжиге 1100-1200 °C и какой был эффект на предел текучести",
        "out": {
            "intent": "experiment_lookup",
            "materials": [{"raw": "ХН77ТЮР", "match": "ХН77ТЮР"}],
            "modes": [{"name": "отжиг", "params": [
                {"name": "temperature", "min": 1100, "max": 1200, "unit": "°C"}
            ]}],
            "properties": [{"raw": "предел текучести", "match": "σ_0.2"}],
            "equipment": [], "authors": [], "teams": [],
            "time_range": None, "tags": [], "open_questions": []
        }
    },
    {
        "q": "как со временем менялась коррозионная стойкость никелевых анодов",
        "out": {
            "intent": "history",
            "materials": [{"raw": "никелевые аноды", "match": None}],
            "modes": [], "properties": [
                {"raw": "коррозионная стойкость", "match": "corrosion_resistance"}
            ],
            "equipment": [], "authors": [], "teams": [],
            "time_range": None, "tags": [],
            "open_questions": ["Какой именно никелевый анод имеется в виду?"]
        }
    },
    {
        "q": "Литературный обзор методов очистки шахтных вод горно-рудных предприятий",
        "out": {
            "intent": "literature_review",
            "materials": [{"raw": "шахтные воды", "match": None}],
            "modes": [{"name": "очистка", "params": []}],
            "properties": [],
            "equipment": [], "authors": [], "teams": [],
            "time_range": None, "tags": ["mine_water"], "open_questions": []
        }
    },
    {
        "q": "сравни электролиз при 50 и 80 градусах по выходу по току",
        "out": {
            "intent": "comparison",
            "materials": [],
            "modes": [
                {"name": "электролиз", "params": [
                    {"name": "temperature", "value": 50, "unit": "°C"}]},
                {"name": "электролиз", "params": [
                    {"name": "temperature", "value": 80, "unit": "°C"}]}
            ],
            "properties": [{"raw": "выход по току", "match": "current_efficiency"}],
            "equipment": [], "authors": [], "teams": [],
            "time_range": None, "tags": [], "open_questions": []
        }
    }
]


def build_prompt(question, known_materials=None, known_properties=None, known_modes=None):
    """Собирает итоговый текст промпта с few-shot."""
    import json
    parts = [
        "СХЕМА JSON:",
        SCHEMA,
        "",
        "ПРИМЕРЫ:",
    ]
    for ex in EXAMPLES:
        parts.append(f"Вопрос: {ex['q']}")
        parts.append("Ответ:")
        parts.append(json.dumps(ex["out"], ensure_ascii=False, indent=2))
        parts.append("")
    if known_materials:
        parts.append("Известные коды материалов (пример): " + ", ".join(known_materials[:30]))
    if known_properties:
        parts.append("Известные свойства: " + ", ".join(known_properties[:30]))
    if known_modes:
        parts.append("Известные режимы: " + ", ".join(known_modes[:30]))
    parts.append("")
    parts.append(f"Вопрос: {question}")
    parts.append("Ответ (только JSON):")
    return "\n".join(parts)

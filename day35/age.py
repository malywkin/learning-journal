"""
День 35 — расчёт «где сейчас ребёнок» и какие рубрики дайджеста собирать.

Это INPUT нашего пайплайна по §12 конспекта (Trigger → INPUT → Agent → Output):
триггер (планировщик) будит систему, а вопрос к базе формулирует не человек, а
ВОЗРАСТ ребёнка. Здесь возраст превращается в «неделю» и в список рубрик.

Две фазы — переключение автоматическое по данным (config из .env):
  • дата рождения НЕ известна  → «беременность»: считаем срок гестации от ПДР;
  • дата рождения известна      → «жизнь»: считаем недели/месяцы от рождения.

Каданс (как у гос-программы NHS Best Start, из брифа Дня 35): беременность — недельно;
жизнь первые 12 недель — недельно; дальше — помесячно. Официального ПОнедельного
гайда для младенца ни у кого нет, поэтому после 12 недель режем по месяцам.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import config

GESTATION_DAYS = 280          # доношенная беременность = 40 недель от последней менструации
NEWBORN_DAYS = 28             # «новорождённый» — первые 4 недели
WEEKLY_LIFE_DAYS = 84         # первые 12 недель жизни шлём недельно, дальше помесячно


@dataclass
class AgeInfo:
    phase: str                # "pregnancy" | "life"
    label: str                # человеку: «39 недель 5 дней беременности» / «3 недели жизни»
    unit: str                 # "week" | "month" — единица каданса
    n: int                    # номер недели (беременность/жизнь) или месяца
    days: int = 0             # полный возраст в днях (для жизни) / срок гестации в днях
    rubrics: list[dict] = field(default_factory=list)


# ---------- Рубрикатор: какие темы собирать в заметку под фазу/возраст ----------
# query — вопрос к корпусу гайдлайнов (bge-m3 мультиязычный: русский запрос по
# английскому тексту находит, проверено Днями 21–24). Каждая рубрика → один RAG-прогон.
def _pregnancy_rubrics(week: int) -> list[dict]:
    common = [
        {"key": "baby_now", "title": "Что сейчас с малышом",
         "query": f"развитие плода на {week} неделе беременности, что происходит с ребёнком"},
    ]
    if week >= 37:  # доношенная — фокус на роды
        return common + [
            {"key": "signs_labour", "title": "Признаки родов — когда ехать",
             "query": "признаки начала родов, схватки, отошли воды, когда звонить в роддом"},
            {"key": "prepare", "title": "Подготовка к родам",
             "query": "как подготовиться к родам, что взять, латентная фаза, что делать дома"},
            {"key": "red_flags_preg", "title": "Тревожные признаки — срочно к врачу",
             "query": "когда срочно звонить акушерке, кровотечение, ребёнок меньше шевелится, срочная помощь"},
        ]
    return common + [  # ранние недели — симптомы и тревожные признаки
        {"key": "symptoms", "title": "Симптомы этой недели",
         "query": f"обычные симптомы и самочувствие на {week} неделе беременности"},
        {"key": "red_flags_preg", "title": "Тревожные признаки — срочно к врачу",
         "query": "когда срочно звонить акушерке, кровотечение, ребёнок меньше шевелится"},
    ]


def _life_rubrics(week: int, month: int, newborn: bool) -> list[dict]:
    dev_q = (f"развитие и вехи ребёнка в {month} месяца, что малыш умеет"
             if not newborn else "развитие новорождённого в первые недели, что умеет")
    return [
        {"key": "dev_now", "title": "Развитие и вехи",
         "query": dev_q},
        {"key": "feeding", "title": "Кормление",
         "query": ("кормление новорождённого, грудное вскармливание, сколько и как часто"
                   if newborn else f"кормление ребёнка в {month} месяца, признаки достаточного питания")},
        {"key": "safe_sleep", "title": "Безопасный сон",
         "query": "безопасный сон младенца, снижение риска СВДС, на спине, своя кроватка"},
        {"key": "red_flags_baby", "title": "Когда срочно к врачу",
         "query": "тревожные признаки болезни у младенца, когда срочно вызывать врача, высокая температура, вялость"},
    ]


# ---------- Главный расчёт ----------
def baby_age(today: date | None = None) -> AgeInfo:
    """Дата → фаза, номер недели/месяца, человекочитаемая подпись и список рубрик."""
    today = today or date.today()

    # --- режим «жизнь» (дата рождения известна) ---
    if config.BABY_BIRTH_DATE:
        days = (today - config.BABY_BIRTH_DATE).days
        days = max(days, 0)
        life_week = days // 7
        life_month = days // 30
        newborn = days < NEWBORN_DAYS
        if days < WEEKLY_LIFE_DAYS:                       # первые 12 недель — недельно
            unit, n = "week", life_week
            label = "новорождённый, первые дни" if days < 7 else f"{life_week} нед. жизни"
        else:                                             # дальше — помесячно
            unit, n = "month", life_month
            label = f"{life_month} мес. жизни"
        return AgeInfo(phase="life", label=label, unit=unit, n=n, days=days,
                       rubrics=_life_rubrics(life_week, max(life_month, 1), newborn))

    # --- режим «беременность» (считаем от ПДР) ---
    if config.BABY_DUE_DATE:
        gest_days = GESTATION_DAYS - (config.BABY_DUE_DATE - today).days
        gest_days = max(gest_days, 0)
        week = gest_days // 7
        rem = gest_days % 7
        label = f"{week} нед." + (f" {rem} дн." if rem else "") + " беременности"
        if gest_days >= 294:                              # 42+ недель — переношенная
            label += " (переношенная — под наблюдением)"
        return AgeInfo(phase="pregnancy", label=label, unit="week", n=week,
                       days=gest_days, rubrics=_pregnancy_rubrics(week))

    # --- ни то ни другое: даты не заданы ---
    return AgeInfo(phase="unknown", label="даты ребёнка не заданы (см. .env)",
                   unit="week", n=0, rubrics=[])


if __name__ == "__main__":
    info = baby_age()
    print(f"Фаза:    {info.phase}")
    print(f"Возраст: {info.label}  (единица каданса: {info.unit}, n={info.n}, дней={info.days})")
    print(f"Рубрик:  {len(info.rubrics)}")
    for r in info.rubrics:
        print(f"  • {r['title']}  ←  «{r['query']}»")

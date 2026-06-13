"""День 10 — демо: один сценарий сбора ТЗ через три стратегии + сравнение.

Ровно то, что просит задание: «прогнать сценарий на каждой стратегии, сравнить
качество / стабильность / расход токенов / удобство».

Подопытный сценарий (сбор ТЗ): в НАЧАЛЕ клиент диктует жёсткие рамки (бюджет
500 000 ₽, дедлайн 14 марта), дальше идёт нейтральный разговор про дизайн
(наполнитель), который выталкивает рамки за окно. В конце спрашиваем про бюджет
и срок — доживёт ли факт?

Два «героя» на ОДНОМ диалоге (окно vs facts — это сопоставимая пара по оси
«что слать»):
  window — SlidingWindow: помнит только последние N → рамки выпали → ТЕРЯЕТ факт.
  facts  — StickyFacts: рамки выписаны на карточку и едут всегда → факт ДОЖИВАЕТ;
           платит за это лишним вызовом LLM на каждую реплику.

Ветки — отдельный жанр (не про «что слать»), поэтому им отдельная демонстрация
run_branching(): общий ствол ТЗ → закладка → две ветки (премиум/бюджет) → каждая
помнит СВОЮ линию, но обе помнят общий ствол. Изоляция, а не экономия.

Честность по токенам (как в Дне 9): кривую входа по ходам считаем ПРИКИДКОЙ
(tiktoken), чтобы не жечь вызов на каждый ход. А финальный ответ «вспомни» и
обновления карточки фактов — РЕАЛЬНЫЕ вызовы (usage с сервера = истина).
"""
from strategies import Branching, SlidingWindow, StickyFacts
from tokens import estimate_messages, normalize_usage

FACT_BUDGET = "500 000"
FACT_DEADLINE = "14 марта"
RECALL_Q = ("Напомни конкретными цифрами: какой у проекта бюджет и какой дедлайн? "
            "Если не знаешь — так и скажи, не выдумывай.")


def build_dialog(filler_turns=8):
    """Сценарий сбора ТЗ: рамки в начале + нейтральный наполнитель про дизайн."""
    history = [
        {"role": "user",
         "content": "Стартуем ТЗ на лендинг. Бюджет строго 500 000 рублей, "
                    "дедлайн — 14 марта. Зафиксируй эти рамки."},
        {"role": "assistant",
         "content": "Зафиксировал рамки: бюджет 500 000 ₽, дедлайн 14 марта."},
    ]
    topics = [
        "Какие шрифты лучше для строгого корпоративного лендинга?",
        "Нужна ли тёмная тема — стоит ли её делать?",
        "Посоветуй палитру: основной и акцентный цвет.",
        "Сколько экранов обычно на лендинге услуги?",
        "Какой тон текста выбрать — на «вы» или на «ты»?",
        "Нужен ли блок с отзывами и куда его поставить?",
        "Стоит ли добавлять онлайн-чат на страницу?",
        "Какие метрики отслеживать после запуска?",
        "Как лучше показать кейсы — слайдером или сеткой?",
        "Нужна ли мультиязычность на старте?",
    ][:filler_turns]
    for i, q in enumerate(topics, 1):
        history += [
            {"role": "user", "content": q},
            {"role": "assistant", "content": f"(ответ №{i} по теме «{q[:30]}…»)"},
        ]
    return history


def _input_curve(strategy, system_prompt, history):
    """Прикидка входных токенов по ходам (после каждой реплики пользователя)."""
    curve = []
    for k in range(len(history)):
        if history[k]["role"] != "user":
            continue
        sent = strategy.build(system_prompt, history[:k + 1])
        curve.append(estimate_messages(sent))
    return curve


def _extract_tokens(strategy):
    """Реальные токены обновлений карточки фактов (своя цена facts)."""
    usages = getattr(strategy, "extract_usage", [])
    return sum((normalize_usage(u) or {}).get("total_tokens") or 0 for u in usages)


def run_hero(agent, strategy, system_prompt, history):
    """Прогнать одного героя: (для facts — обновить карточку по всем репликам),
    кривая входа + финальный реальный вопрос «вспомни»."""
    # facts обновляет карточку ПОСЛЕ каждой реплики пользователя — делаем это реально
    if isinstance(strategy, StickyFacts):
        for m in history:
            if m["role"] == "user":
                strategy.update(m["content"])

    curve = _input_curve(strategy, system_prompt, history)            # прикидки по ходам
    full = history + [{"role": "user", "content": RECALL_Q}]
    sent = strategy.build(system_prompt, full)
    reply, usage = agent.complete(sent)
    u = normalize_usage(usage)
    view = strategy.view()
    return {
        "curve_estimate": curve,
        "total_input_estimate": sum(curve),
        "final_input_real": (u or {}).get("prompt_tokens"),
        "extract_tokens_real": _extract_tokens(strategy),     # цена facts (0 у окна)
        "facts": view.get("facts", ""),                       # карточка (что выжило)
        "keep_last": view.get("keep_last"),
        "reply": (reply or "").strip(),
        "fact_recalled": _recalled(reply),
        "fact_in_payload": any(FACT_BUDGET in m["content"] for m in sent),
    }


def _recalled(reply):
    """Проверка «вспомнил факт», устойчивая к разным пробелам/формату числа.
    Модель печатает 500 000 то с обычным, то с неразрывным пробелом — сравниваем
    по цифрам без пробелов, а дедлайн — по дню и месяцу."""
    r = (reply or "")
    digits = "".join(ch for ch in r if ch.isdigit())
    budget_ok = "500000" in digits
    deadline_ok = "14" in r and "март" in r.lower()
    return budget_ok and deadline_ok


def run_compare(agent, filler_turns=8, keep_last=6):
    """Сравнить окно vs facts на одном сценарии сбора ТЗ."""
    history = build_dialog(filler_turns)
    sp = agent.system_prompt
    heroes = {
        "window": run_hero(agent, SlidingWindow(keep_last), sp, history),
        "facts": run_hero(agent, StickyFacts(agent.make_extractor(), keep_last), sp, history),
    }
    return {
        "budget": FACT_BUDGET,
        "deadline": FACT_DEADLINE,
        "turns": len(history) // 2,
        "keep_last": keep_last,
        "heroes": heroes,
    }


# ── Ветки: отдельная демонстрация (изоляция, не экономия) ──────────────────
BASE_TZ = [
    {"role": "user",
     "content": "ТЗ на лендинг. Бюджет 500 000 ₽, дедлайн 14 марта. Это общие рамки."},
    {"role": "assistant",
     "content": "Принял общие рамки: бюджет 500 000 ₽, дедлайн 14 марта."},
]
BRANCH_Q = "Коротко: что мы решили по дизайну и какой у нас бюджет?"


def run_branching(agent):
    """Собрать общий ствол ТЗ → закладка → две ветки → показать изоляцию.

    Ветка A (премиум) и ветка B (бюджет) стартуют от ОДНОЙ закладки. Каждая
    помнит свою линию по дизайну, но ОБЕ помнят общий ствол (бюджет 500к)."""
    br = Branching()
    agent.set_context(br)

    for m in BASE_TZ:                       # наполняем общий ствол (без вызовов)
        br.add(m)
    trunk_at = br.checkpoint("ТЗ собрано")   # ЗАКЛАДКА: ствол заморожен

    br.fork("A (премиум)")
    br.fork("B (бюджет)")

    # Ветка A — задаём направление и спрашиваем (реальные вызовы)
    br.switch("A (премиум)")
    a_dir = agent.send("Делаем ПРЕМИУМ: кастомный дизайн, анимации, индивидуальная вёрстка.")
    a_recall = agent.send(BRANCH_Q)

    # Ветка B — другое направление от ТОЙ ЖЕ закладки
    br.switch("B (бюджет)")
    b_dir = agent.send("Делаем БЮДЖЕТНО: готовый шаблон, минимум кастома.")
    b_recall = agent.send(BRANCH_Q)

    # Проверка изоляции: вернёмся в A — её линия цела, B её не задела
    br.switch("A (премиум)")
    a_again = agent.send("Ещё раз: мы про шаблон или про кастом?")

    return {
        "trunk_len": trunk_at,
        "view": br.view(),
        "A_direction": (a_dir or "").strip(),
        "A_recall": (a_recall or "").strip(),
        "A_after_switchback": (a_again or "").strip(),
        "B_direction": (b_dir or "").strip(),
        "B_recall": (b_recall or "").strip(),
    }

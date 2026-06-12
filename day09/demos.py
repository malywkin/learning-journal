"""День 9 — демо: БЕЗ сжатия vs СО сжатием. Ровно то, что просит задание.

Подопытный диалог: в НАЧАЛЕ клиент диктует факт (проект «Гриффин», номер 4471,
дедлайн 14 марта), дальше идёт нейтральный трёп (наполнитель), который выталкивает
факт за окно. В конце спрашиваем про факт: вспомнит ли агент?

Три героя на ОДНОМ и том же диалоге:
  plain — NoCompression: помнит всё (факт в полной истории), но ВХОД растёт каждый
          ход — платим за всю историю заново.
  smart — RollingSummary + DEFAULT_GUARDRAIL («сохрани имена/числа/даты»): факт
          переезжает в копилку и ВЫЖИВАЕТ; вход не растёт лавиной.
  naive — RollingSummary + NAIVE_GUARDRAIL («кратко перескажи»): конкретика
          вымывается — факт ТЕРЯЕТСЯ. Это иллюстрация «когда summary ВРЕДИТ».

Что честно: кривую входа по ходам считаем ПРИКИДКОЙ (tiktoken, estimate_messages) —
чтобы не жечь по вызову на каждый ход. А итоговый ответ «вспомни» и саму
суммаризацию делаем РЕАЛЬНЫМИ вызовами (usage с сервера = истина).
"""
from compress import DEFAULT_GUARDRAIL, NAIVE_GUARDRAIL, NoCompression, RollingSummary
from tokens import estimate_messages, normalize_usage

FACT_NUMBER = "4471"
FACT_HUMAN = "проект «Гриффин», внутренний номер 4471, дедлайн 14 марта"
RECALL_Q = "Напомни: как называется наш проект, какой у него внутренний номер и дедлайн?"


def build_dialog(filler_turns=10):
    """Сценарный диалог: факт в начале + нейтральный наполнитель, выталкивающий его."""
    history = [
        {"role": "user",
         "content": "Зафиксируй детали проекта: название «Гриффин», "
                    "внутренний номер 4471, дедлайн — 14 марта."},
        {"role": "assistant",
         "content": "Зафиксировал: проект «Гриффин», номер 4471, дедлайн 14 марта."},
    ]
    topics = [
        "Какая погода обычно в Лиссабоне весной?",
        "Посоветуй книгу по тайм-менеджменту.",
        "В чём разница между чаем улун и зелёным?",
        "Как по-английски будет «договор аренды»?",
        "Дай идею для подарка коллеге на день рождения.",
        "Сколько длится перелёт Москва — Стамбул?",
        "Что приготовить на ужин из курицы за 20 минут?",
        "Объясни простыми словами, что такое инфляция.",
        "Какие есть приёмы борьбы с прокрастинацией?",
        "Назови три интересных факта о космосе.",
        "Как правильно хранить кофе в зёрнах?",
        "Посоветуй маршрут прогулки по выходным.",
    ][:filler_turns]
    for i, q in enumerate(topics, 1):
        history += [
            {"role": "user", "content": q},
            {"role": "assistant", "content": f"(ответ №{i} по теме «{q[:30]}…»)"},
        ]
    return history


def _input_curve(strategy, system_prompt, history):
    """Прокрутить историю по ходам (после каждой реплики пользователя) и записать
    ПРИКИДКУ входных токенов того, что ушло бы в модель. Заодно build() по дороге
    реально СВОРАЧИВАЕТ старое в копилку (тут и тратятся вызовы суммаризатора)."""
    curve = []
    for k in range(len(history)):
        if history[k]["role"] != "user":
            continue
        sent = strategy.build(system_prompt, history[:k + 1])
        curve.append(estimate_messages(sent))
    return curve


def _summ_tokens(strategy):
    """Реальные токены, потраченные на суммаризацию (своя цена сжатия)."""
    usages = getattr(strategy, "summ_usage", [])
    return sum((normalize_usage(u) or {}).get("total_tokens") or 0 for u in usages)


def run_hero(agent, strategy, system_prompt, history):
    """Прогнать одного героя: кривая входа + финальный реальный вопрос «вспомни»."""
    curve = _input_curve(strategy, system_prompt, history)            # прикидки по ходам
    # финальный ход: добавляем вопрос «вспомни» и делаем РЕАЛЬНЫЙ вызов
    full = history + [{"role": "user", "content": RECALL_Q}]
    sent = strategy.build(system_prompt, full)
    reply, usage = agent.complete(sent)
    u = normalize_usage(usage)
    view = strategy.view()
    return {
        "curve_estimate": curve,                       # прикидка входа по ходам
        "total_input_estimate": sum(curve),            # суммарный вход за диалог (прикидка)
        "final_input_real": (u or {}).get("prompt_tokens"),   # РЕАЛЬНЫЙ вход финального хода
        "summary_tokens_real": _summ_tokens(strategy),        # РЕАЛЬНАЯ цена суммаризации
        "summarizations": view.get("summarizations", 0),
        "summary": view.get("summary", ""),            # сама копилка (что выжило)
        "reply": (reply or "").strip(),
        "fact_recalled": FACT_NUMBER in (reply or ""), # вспомнил реальный номер?
        "fact_in_payload": any(FACT_NUMBER in m["content"] for m in sent),  # факт был во входе?
    }


def run_compare(agent, filler_turns=10, keep_last=4, trigger=10):
    """Сравнить три режима на одном диалоге. Возвращает структуру для печати/веба."""
    history = build_dialog(filler_turns)
    sp = agent.system_prompt
    summarizer = agent.make_summarizer()

    heroes = {
        "plain": run_hero(agent, NoCompression(), sp, history),
        "smart": run_hero(
            agent, RollingSummary(summarizer, keep_last, trigger, DEFAULT_GUARDRAIL), sp, history),
        "naive": run_hero(
            agent, RollingSummary(summarizer, keep_last, trigger, NAIVE_GUARDRAIL), sp, history),
    }
    return {
        "fact": FACT_HUMAN,
        "number": FACT_NUMBER,
        "turns": len(history) // 2,
        "keep_last": keep_last,
        "trigger": trigger,
        "heroes": heroes,
    }

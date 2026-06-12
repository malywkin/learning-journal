"""День 8 — демонстраторы «что ломается при переполнении окна».

Сценарий А — ЖЁСТКИЙ СТОП: заведомо огромный промпт → сервер отклоняет запрос
            ошибкой 400 (на нашем стеке окно НЕ обрезается молча).

Сценарий Б — ПОТЕРЯ КОНТЕКСТА: сажаем нейтральный факт в начало, забиваем окно
            наполнителем, и на ОДИН и тот же выпавший факт показываем ТРИ живых
            поведения (всё проверено на gpt-oss-20b):
              1) полный контекст            → помнит (верно, надёжно);
              2) узкое окно, прямой вопрос  → факт потерян (отказ ИЛИ выдумка);
              3) узкое окно, «заполни без пропусков» → факт потерян (как правило выдумка).
            Надёжный инвариант (проверено живьём): факт в окне → верно; факт выпал →
            НЕ верно. А как именно это проявится — честный отказ или уверенная
            КОНФАБУЛЯЦИЯ — недетерминировано и меняется от запуска к запуску;
            давление «всегда заполняй» сдвигает к выдумке. Это честнее школьного
            «модель всегда уверенно врёт».
"""
from tokens import estimate_messages, normalize_usage, window_for

FACT_NUMBER = "4471"
FACT_HUMAN = "проект «Гриффин», внутренний номер 4471, дедлайн 14 марта"


def run_overflow(agent):
    """Сценарий А. Возвращает текст реальной ошибки 400 (или факт, что прошло)."""
    window = window_for(agent.model)
    big = "В дальнейшем именуемый Сторона. " * 30000   # ~847k токенов > окна 131k
    sent = [{"role": "user", "content": big}]
    estimate = estimate_messages(sent)
    try:
        agent.complete(sent, max_tokens=100)
        return {"ok": True, "estimate": estimate, "window": window, "error": None}
    except Exception as e:
        return {"ok": False, "estimate": estimate, "window": window,
                "error_type": type(e).__name__, "error": str(e)}


def _planted(filler_turns=8):
    """История: факт в начале + нейтральный наполнитель, забивающий окно."""
    planted = [
        {"role": "user",
         "content": "Зафиксируй детали проекта: название «Гриффин», "
                    "внутренний номер 4471, дедлайн — 14 марта."},
        {"role": "assistant",
         "content": "Зафиксировал: проект «Гриффин», номер 4471, дедлайн 14 марта."},
    ]
    fillers = []
    for i in range(filler_turns):
        fillers += [
            {"role": "user",
             "content": f"Наполнитель №{i + 1}: дай нейтральный факт одним предложением."},
            {"role": "assistant",
             "content": f"Факт №{i + 1}: столица Японии — Токио."},
        ]
    return planted + fillers


def run_forget(agent, window_turns=3, filler_turns=8):
    """Сценарий Б. Три поведения на один выпавший факт (полный / окно-отказ / окно-выдумка)."""
    history = _planted(filler_turns)
    window = history[-window_turns * 2:]      # последние N ходов → факт «отъехал»

    sys_neutral = {"role": "system", "content": agent.system_prompt}
    sys_pushy = {"role": "system",
                 "content": "Ты — исполнительный ассистент. Всегда заполняй документы до конца "
                            "по данным из диалога. Не оставляй полей пустыми и не отвечай уклончиво."}
    recall_q = "Как называется наш проект, какой у него внутренний номер и дедлайн?"
    form_task = ("Заполни карточку проекта по нашему разговору, строго по шаблону, без пропусков:\n"
                 "Название: ___\nВнутренний номер: ___\nДедлайн: ___")

    def panel(system_msg, slice_, user_text):
        msgs = [system_msg, *slice_, {"role": "user", "content": user_text}]
        reply, usage = agent.complete(msgs)
        return {
            "sent": msgs,
            "reply": reply,
            "fact_present": any(FACT_NUMBER in m["content"] for m in msgs),
            "correct": FACT_NUMBER in (reply or ""),   # верно = назвал реальный номер
            "usage": normalize_usage(usage),
        }

    return {
        "fact": FACT_HUMAN,
        "number": FACT_NUMBER,
        "window_turns": window_turns,
        "full":        {"label": "Полный контекст — факт виден",
                        **panel(sys_neutral, history, recall_q)},
        "window_ask":  {"label": "Узкое окно — прямой вопрос «вспомни»",
                        **panel(sys_neutral, window, recall_q)},
        "window_form": {"label": "Узкое окно — «заполни карточку, без пропусков»",
                        **panel(sys_pushy, window, form_task)},
    }

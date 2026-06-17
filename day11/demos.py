"""День 11 — демо: что попадает в каждый слой и как это меняет ответ.

Ровно две проверки из задания:
  • «какие данные попадают в каждый слой» → прогоняем сценарий, смотрим трассу
    роутера и итог трёх слоёв (run_layers);
  • «как это влияет на ответы» → один и тот же вопрос задаём ДВАЖДЫ: с
    подмешанной долговременной памятью и без неё. Разный ответ = слой работает
    (run_influence). Плюс run_new_task: новая задача чистит рабочую, профиль живёт.

Сценарий — сбор задачи, где намеренно перемешаны три типа фактов:
  • про пользователя (роль, стиль ответа, постоянный запрет) → долговременная;
  • про задачу (стек проекта, бюджет, дедлайн) → рабочая;
  • проходная болтовня → никуда (роутер на первой развилке говорит «нечего»).

Честность по токенам: вызовы роутера и оба финальных ответа — РЕАЛЬНЫЕ вызовы LLM
(usage с сервера). Ничего не подкручиваем.
"""

# Реплики сценария. Помечаем ОЖИДАЕМЫЙ слой — чтобы в выводе сверить, угадал ли роутер
# (граница «задача/пользователь» местами размытая — честно покажем и промахи).
SCRIPT = [
    ("Я senior Android-разработчик. Отвечай мне максимально кратко — два-три "
     "предложения, без таблиц и примеров кода.", "долговременная"),
    ("Стартуем сервис авторизации. В этом проекте стек строго Kotlin и Ktor, "
     "бюджет 300 000 рублей, дедлайн 30 марта.", "рабочая"),
    ("Терпеть не могу RxJava — никогда мне его не предлагай.", "долговременная"),
    ("Окей, спасибо, дальше.", "ничего"),
]

# Финальный вопрос — обычная просьба совета. Заметный сигнал влияния профиля —
# КРАТКОСТЬ ответа: в профиле лежит «отвечай кратко, без таблиц». С профилем ответ
# короткий; без профиля модель по своей привычке выкатывает простыню с таблицей.
INFLUENCE_Q = ("Посоветуй подход для асинхронности и реактивных потоков данных "
               "в этом модуле. Назови конкретную библиотеку.")


def _has_table(text):
    return "|" in (text or "") or "```" in (text or "")


def run_layers(agent):
    """Прогнать сценарий и показать, ЧТО осело в каждом слое (+ трасса роутера)."""
    steps = []
    for msg, expected in SCRIPT:
        trace = agent.memory.observe(msg)          # краткосрочная + роутинг по слоям
        steps.append({
            "message": msg,
            "expected": expected,
            "to_working": trace["to_working"],
            "to_longterm": trace["to_longterm"],
            "saved_nothing": trace["saved_nothing"],
            "parsed": trace["parsed"],
        })
    v = agent.memory.view()
    return {
        "steps": steps,
        "short_count": len(v["short"]["messages"]),
        "working": v["working"]["text"],
        "longterm": v["longterm"]["text"],
    }


def run_influence(agent):
    """Один вопрос — два ответа: с долговременной памятью и без.

    КЛЮЧЕВОЕ (урок Дней 9–10): чтобы честно проверить именно ДОЛГОВРЕМЕННЫЙ слой,
    очищаем краткосрочную (диалог) — иначе факты профиля видны модели прямо из окна
    диалога, и слой не при чём. Это «новая сессия того же пользователя»: диалог
    пуст, профиль жив ТОЛЬКО в долговременной памяти. Рабочую (стек задачи) и
    профиль оставляем; меняем РОВНО один рычаг — долговременную."""
    agent.memory.short.clear()                 # новая сессия: диалога нет
    with_lt = agent.send(INFLUENCE_Q, use_longterm=True)
    agent.memory.short.clear()                 # снова чистый диалог для второго прогона
    without_lt = agent.send(INFLUENCE_Q, use_longterm=False)
    agent.memory.short.clear()
    return {
        "question": INFLUENCE_Q,
        "longterm_card": agent.memory.longterm.text,
        "with_longterm": (with_lt or "").strip(),
        "without_longterm": (without_lt or "").strip(),
        "len_with": len((with_lt or "").strip()),
        "len_without": len((without_lt or "").strip()),
        "table_with": _has_table(with_lt),
        "table_without": _has_table(without_lt),
    }


def run_new_task(agent):
    """Показать разницу слоёв на деле: новая задача обнуляет рабочую и диалог,
    долговременная остаётся в силе."""
    before = {"working": agent.memory.working.text, "longterm": agent.memory.longterm.text}
    agent.memory.new_task()
    after = {"working": agent.memory.working.text, "longterm": agent.memory.longterm.text}
    return {"before": before, "after": after,
            "working_cleared": after["working"] == "",
            "longterm_kept": after["longterm"] == before["longterm"]}

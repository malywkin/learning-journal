"""День 12 — демо: как профиль меняет ответ и что ассистент учитывает сам.

Три проверки из задания:
  • «ответы для разных профилей» → run_two_profiles: ОДИН и тот же вопрос задаём
    при двух разных профилях (юрист / разработчик). Разные ответы = персонализация
    работает.
  • «что ассистент учитывает автоматически» → run_auto_notice: ведём обычный диалог,
    нигде не командуя «запомни», и смотрим, что само осело в профиль (noticed).
  • разделение слоёв → run_new_task: новая задача чистит рабочую и диалог, профиль
    остаётся (он про человека, а не про задачу).

Честность по токенам: профиль для двух прогонов задаём НАПРЯМУЮ (stated.set), чтобы
сравнение было детерминированным и не зависело от фантазии нормализатора; сами ответы
и роутер — реальные вызовы LLM.
"""

# Два профиля для сравнения. Разный стиль/формат/ограничения — на одном вопросе
# разница в ответе должна быть видна невооружённым глазом.
PROFILE_LAWYER = (
    "Роль: юрист, не программист\n"
    "Стиль: простыми словами, без технического жаргона\n"
    "Формат: ровно один абзац, не более 4 предложений; бытовая аналогия; "
    "без списков, без заголовков, без кода, без таблиц\n"
    "Ограничения: не показывать код и не использовать термины без расшифровки"
)
PROFILE_DEV = (
    "Роль: backend-разработчик на Python\n"
    "Стиль: по делу, без вводных фраз\n"
    "Формат: сначала 3 пункта маркированного списка, затем обязательно блок кода "
    "```python``` с коротким примером\n"
    "Ограничения: не объяснять азы, не использовать бытовые аналогии"
)

# Нейтральный вопрос: оба профиля могут на него ответить, но ПО-РАЗНОМУ (форма/стиль).
COMPARE_Q = "Что такое кэширование и когда его стоит применять?"


def _has_code(text):
    return "```" in (text or "") or "def " in (text or "")


def run_two_profiles(agent, q=COMPARE_Q,
                     profile_a=PROFILE_LAWYER, profile_b=PROFILE_DEV,
                     name_a="юрист", name_b="разработчик"):
    """Один вопрос — два профиля — два ответа. Перед каждым прогоном чистим диалог
    (новая сессия), чтобы на ответ влиял ТОЛЬКО профиль, а не прошлые реплики."""
    def ask_with(profile):
        agent.memory.short.clear()                 # чистый диалог: влияет только профиль
        agent.memory.profile.stated.set(profile)
        return (agent.send(q, use_profile=True) or "").strip()

    ans_a = ask_with(profile_a)
    ans_b = ask_with(profile_b)
    agent.memory.short.clear()
    return {
        "question": q,
        "profile_a": {"name": name_a, "card": profile_a, "answer": ans_a,
                      "len": len(ans_a), "has_code": _has_code(ans_a)},
        "profile_b": {"name": name_b, "card": profile_b, "answer": ans_b,
                      "len": len(ans_b), "has_code": _has_code(ans_b)},
    }


# Диалог, где пользователь НЕ командует «запомни», но между делом выдаёт предпочтения.
# Роутер должен сам выудить их в профиль (noticed) — это и есть «учитывает автоматически».
AUTO_SCRIPT = [
    "Слушай, отвечай мне покороче, я не люблю длинные простыни.",
    "И вообще не предлагай мне Java — терпеть её не могу.",
    "Я фронтендер, работаю в основном с TypeScript.",
    "Окей, спасибо.",
]


def run_auto_notice(agent):
    """Прогнать обычный диалог и показать, что профиль (noticed) наполнился САМ,
    без явных команд запоминания."""
    steps = []
    for msg in AUTO_SCRIPT:
        trace = agent.memory.observe(msg)
        steps.append({"message": msg, "to_noticed": trace["to_noticed"],
                      "saved_nothing": trace["saved_nothing"]})
    return {"steps": steps, "noticed": agent.memory.profile.noticed.text}


def run_new_task(agent):
    """Новая задача обнуляет рабочую и диалог, профиль (обе части) остаётся в силе."""
    before = {"working": agent.memory.working.text,
              "stated": agent.memory.profile.stated.text,
              "noticed": agent.memory.profile.noticed.text}
    agent.memory.new_task()
    after = {"working": agent.memory.working.text,
             "stated": agent.memory.profile.stated.text,
             "noticed": agent.memory.profile.noticed.text}
    return {"before": before, "after": after,
            "working_cleared": after["working"] == "",
            "profile_kept": (after["stated"] == before["stated"]
                             and after["noticed"] == before["noticed"])}

"""День 15 — СЕРДЦЕ ДНЯ: ворота на переходах между состояниями.

Рельсы (task_state.ALLOWED) отвечают на вопрос «нарисована ли стрелка?». Ворота отвечают на
вопрос «а ПРОПУСК-то есть?» — выполнены ли предусловия конкретного перехода. Без ворот
машина состояний Дня 13 пустила бы planning → execution даже с пустым планом: стрелка-то
есть. Ворота это запрещают: нельзя в «Реализацию» без ОДОБРЕННОГО плана, нельзя в «Готово»
без вердикта PASS от панели.

Каскад по разведке 2026 (futureagi, OpenAI guardrails): на горячем пути — дешёвые
ДЕТЕРМИНИРОВАННЫЕ проверки («артефакт есть», «флаг одобрения», «вердикт PASS», блок-лист
инвариантов). Смысловой вопрос («план вообще достаточно полон, чтобы по нему писать?»)
отдаётся LLM/панели — но это уже не здесь, а в swarm.py: панель ПРОИЗВОДИТ вердикт во время
этапа validation, а ворота лишь читают готовый вердикт. Так «пол» остаётся детерминированным.

Каждая проверка — функция state → (ok, reason). Ворота перехода = список проверок; переход
открыт, если ВСЕ проверки прошли (а не большинство — переход «обмазан валидациями»).
"""
from invariants import SYSTEM_INVARIANTS, deterministic_check
from task_state import DONE, EXECUTION, PLANNING, VALIDATION


# ── элементарные предусловия (детерминированные, без сети) ──────────────────
def plan_exists(state):
    ok = bool(state.artifacts.get("plan", "").strip())
    return ok, "план составлен" if ok else "плана ещё нет"


def plan_approved(state):
    ok = bool(state.plan_approved)
    return ok, "план одобрен" if ok else "план НЕ одобрен (нельзя в реализацию)"


def draft_exists(state):
    ok = bool(state.artifacts.get("draft", "").strip())
    return ok, "черновик есть" if ok else "черновика ещё нет"


def draft_clean(state):
    """Инвариантные ворота (День 14): черновик не нарушает жёстких правил."""
    hits = deterministic_check(state.artifacts.get("draft", ""), SYSTEM_INVARIANTS)
    if hits:
        ids = ", ".join(h["id"] for h in hits)
        return False, f"черновик нарушает инвариант ({ids})"
    return True, "инварианты не нарушены"


def validation_passed(state):
    ok = state.validation.get("decision") == "pass"
    d = state.validation.get("decision")
    label = {"pass": "панель: PASS", "fail": "панель: на доработку",
             "abstain": "панель воздержалась", None: "проверки ещё не было"}
    return ok, label.get(d, str(d))


def validation_not_passed(state):
    """Для возврата VALIDATION → EXECUTION: уместен, когда панель НЕ дала чистый PASS."""
    ok = state.validation.get("decision") in ("fail", "abstain")
    return ok, "есть замечания/воздержание панели" if ok else "панель дала PASS — доработка не нужна"


# ── РЕЕСТР ВОРОТ: предусловия на каждую разрешённую стрелку ──────────────────
GATES = {
    (PLANNING, EXECUTION):  [plan_exists, plan_approved],
    (EXECUTION, VALIDATION): [draft_exists, draft_clean],
    (VALIDATION, DONE):      [draft_exists, validation_passed],
    (VALIDATION, EXECUTION): [validation_not_passed],
}


class GateBlocked(Exception):
    """Переход разрешён рельсами, но ворота закрыты (предусловие не выполнено)."""
    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def check_gate(state, to_stage):
    """Прогнать предусловия перехода state.stage → to_stage. Возвращает структуру для UI.

    {transition, passed, checks:[{name,ok,reason}], blocked_by:[reason,...]}.
    Если для пары переходов ворот не задано — считаем открытыми (только рельсы).
    """
    checks = GATES.get((state.stage, to_stage), [])
    rows, blocked = [], []
    for chk in checks:
        ok, reason = chk(state)
        rows.append({"name": chk.__name__, "ok": ok, "reason": reason})
        if not ok:
            blocked.append(reason)
    return {
        "transition": [state.stage, to_stage],
        "passed": not blocked,
        "checks": rows,
        "blocked_by": blocked,
    }

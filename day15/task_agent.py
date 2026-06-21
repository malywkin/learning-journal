"""День 15 — оркестратор: гонит задачу по этапам через ВОРОТА, с роем на проверке.

Паттерн 2026 (Cognition «What's actually working», Anthropic): ОДИН писатель-оркестратор
владеет состоянием и решениями; рой валидаторов — read-only интеллект, который только
отдаёт вердикты. Здесь оркестратор:
  • на каждом этапе зовёт своего воркера (планировщик / составитель) или панель (проверка);
  • двигает этап ТОЛЬКО через _guarded_advance() — единую точку, где сначала проверяются
    ворота (gates.check_gate), и лишь потом срабатывают рельсы (state.advance);
  • на паузе ждёт человека (HITL), а при воздержании панели ПРИНУДИТЕЛЬНО эскалирует;
  • держит потолок доработок (anti-loop), как в Дне 13.

Урок идемпотентности из разведки (LangGraph interrupt / Temporal replay): возобновление
после паузы НЕ повторяет работу — состояние и готовые артефакты поднимаются с диска, а run_*
зовётся только для НОВОГО этапа. Поэтому пауза дёшева и безопасна.
"""
import os
import time

from openai import OpenAI, RateLimitError

from gates import GateBlocked, check_gate
from swarm import panel_validate
from task_state import (ALLOWED, DONE, EXECUTION, PLANNING, VALIDATION, TaskState, TITLE)


PLAN_SYS = (
    "Ты юрист-планировщик. По задаче пользователя составь КОРОТКИЙ план документа: какие "
    "разделы и обязательные условия должны в нём быть и на какие нормы/риски опереться. "
    "4–7 пунктов списком, без воды. Это ПЛАН, а не сам документ."
)
EXEC_SYS = (
    "Ты юрист-составитель. Напиши документ СТРОГО по утверждённому плану — закрой КАЖДЫЙ пункт "
    "плана. Структура с разделами, формулировки по существу. Только текст документа, без "
    "вступлений и пояснений."
)


class TaskAgent:
    def __init__(self, model="openai/gpt-oss-20b:free", client=None,
                 reasoning_effort="low", max_revisions=2):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_revisions = max_revisions
        self.ledger = []
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
            timeout=60,            # клиентский таймаут: зависшее соединение не вешает запрос
        )

    # ── один вызов LLM (не-стрим), retry на лимит ──────────────────────────
    def complete(self, system, user, max_tokens=900, temperature=0):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kwargs = {"model": self.model, "messages": msgs,
                  "max_tokens": max_tokens, "temperature": temperature}
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}
        for attempt in range(4):
            try:
                r = self.client.chat.completions.create(**kwargs)
                self._record(getattr(r, "usage", None))
                return r.choices[0].message.content or ""
            except RateLimitError:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                return "[лимит запросов OpenRouter (429) — подожди минуту и повтори]"
            except Exception as e:
                return f"[ошибка вызова LLM: {e}]"
        return ""

    def _record(self, usage):
        total = getattr(usage, "total_tokens", 0) if usage else 0
        prev = self.ledger[-1]["cumulative"] if self.ledger else 0
        self.ledger.append({"tokens": total, "cumulative": prev + total})

    # ── ЕДИНАЯ точка перехода: сначала ворота, потом рельсы ─────────────────
    def _guarded_advance(self, state, to, reason):
        gate = check_gate(state, to)
        if not gate["passed"]:
            state.blocked(to, "; ".join(gate["blocked_by"]))
            raise GateBlocked(gate["blocked_by"])
        state.advance(to, reason)          # рельсы (IllegalTransition, если стрелки нет)
        return gate

    def try_jump(self, state, to):
        """Безопасная ПРОБА перехода для UI/CLI: открыт ли (рельсы + ворота), без работы.
        Возвращает kind: off_rails (мимо рельсов) | gate_closed (ворота) | open."""
        if to not in ALLOWED.get(state.stage, []):
            return {"ok": False, "kind": "off_rails",
                    "reason": f"стрелки {TITLE[state.stage]} → {TITLE.get(to, to)} нет на карте",
                    "allowed": ALLOWED.get(state.stage, [])}
        gate = check_gate(state, to)
        if not gate["passed"]:
            return {"ok": False, "kind": "gate_closed", "gate": gate,
                    "reason": "; ".join(gate["blocked_by"])}
        return {"ok": True, "kind": "open", "gate": gate}

    # ── контекст для воркера этапа ─────────────────────────────────────────
    def _context(self, state, extra=""):
        a = state.artifacts
        parts = [f"Задача: {state.goal}"]
        if a["plan"]:
            parts.append(f"\nУтверждённый план:\n{a['plan']}")
        if a["draft"] and state.stage in (EXECUTION, VALIDATION):
            parts.append(f"\nТекущий документ:\n{a['draft']}")
        if state.validation.get("reason") and state.stage == EXECUTION:
            parts.append(f"\nЗамечания прошлой проверки: {state.validation['reason']}")
        if extra:
            parts.append(f"\n{extra}")
        return "\n".join(parts)

    # ── РАБОТА текущего этапа ───────────────────────────────────────────────
    def run_current(self, state, human_note=""):
        stage = state.stage
        extra = f"Учти правку человека: {human_note}" if human_note else ""

        if stage == PLANNING:
            plan = self.complete(PLAN_SYS, self._context(state, extra))
            state.record_work(plan, ask=state.ask_between)
            if not state.ask_between:
                state.approve_plan()                  # режим «само»: оркестратор сам одобряет

        elif stage == EXECUTION:
            draft = self.complete(EXEC_SYS, self._context(state, extra))
            state.record_work(draft, ask=state.ask_between)

        elif stage == VALIDATION:
            verdict = panel_validate(self.complete, state.goal,
                                     state.artifacts["plan"], state.artifacts["draft"])
            self._apply_verdict(state, verdict)
        state.save()
        return state

    # ── разобрать вердикт панели и решить, что делать ──────────────────────
    def _apply_verdict(self, state, verdict):
        decision, reason = verdict["decision"], verdict["reason"]
        # потолок доработок: придирки панели не зацикливают (anti-loop, как в Дне 13)
        if decision in ("fail", "abstain") and state.revision >= self.max_revisions:
            decision = "pass"
            reason = "принято по лимиту доработок (%d): %s" % (self.max_revisions, reason)
        # режим «само»: эскалировать некому → воздержание трактуем как доработку
        elif decision == "abstain" and not state.ask_between:
            decision = "fail"
            reason = "воздержание панели → авто-доработка: " + reason
        review = {"pass": "ПРИНЯТО панелью. ", "fail": "НА ДОРАБОТКУ. ",
                  "abstain": "ВОЗДЕРЖАНИЕ панели. "}.get(decision, "") + reason
        state.artifacts["review"] = review
        state.set_validation(decision, verdict["lenses"], reason)
        state.events.append({"kind": "work", "stage": VALIDATION, "text": review})
        if decision == "abstain":
            state.escalate(reason)                    # принудительная пауза к человеку
        elif state.ask_between:                       # pass/fail — пауза на подтверждение (HITL)
            state.awaiting = True
            q = ("Панель: PASS. Одобрить финал?" if decision == "pass"
                 else "Панель нашла пробелы. Вернуть на доработку?")
            state.events.append({"kind": "ask", "stage": VALIDATION, "text": q})

    # ── куда оркестратор хочет шагнуть из паузы ─────────────────────────────
    def _intended(self, state):
        if state.stage == PLANNING:
            return EXECUTION, "план одобрен"
        if state.stage == EXECUTION:
            return VALIDATION, "документ готов"
        if state.stage == VALIDATION:
            return (DONE, "проверка пройдена") if state.validation.get("decision") == "pass" \
                else (EXECUTION, "панель вернула на доработку")
        return None, ""

    # ── человек одобрил паузу → шагнуть по воротам и доработать до след. паузы ─
    def approve(self, state):
        if state.is_done():
            return state
        if state.stage == PLANNING:
            state.approve_plan()                      # заправляем ворота PLANNING → EXECUTION
        self._step_and_drive(state)
        return state

    # ── человек на ВОЗДЕРЖАНИИ панели: принять документ или вернуть ──────────
    def resolve(self, state, accept):
        if not state.escalated:
            return state
        if accept:
            state.validation["decision"] = "pass"     # человек переопределил воздержание
            state.events.append({"kind": "approve", "stage": VALIDATION,
                                "text": "Человек принял документ, несмотря на воздержание панели."})
            state.escalated = False
            self._guarded_advance(state, DONE, "человек принял на воздержании")
        else:
            state.events.append({"kind": "revise", "stage": VALIDATION,
                                "text": "Человек вернул на доработку (воздержание панели)."})
            state.escalated = False
            self._step_and_drive(state, force=EXECUTION, reason="человек вернул на доработку")
        state.save()
        return state

    # ── человек внёс правку: переделать текущий этап ────────────────────────
    def revise(self, state, note):
        if state.stage == VALIDATION:                 # на проверке правка = назад в реализацию
            state.escalated = False
            state.note_revision(note)
            self._step_and_drive(state, force=EXECUTION, reason="правка человека на проверке",
                                 human_note=note)
        else:
            state.note_revision(note)
            self.run_current(state, human_note=note)
        state.save()
        return state

    # ── один шаг по воротам + автопрогон до паузы/финала ────────────────────
    def _step_and_drive(self, state, force=None, reason=None, human_note=""):
        to, why = (force, reason) if force else self._intended(state)
        if to is None:
            return state
        try:
            self._guarded_advance(state, to, why)
        except GateBlocked:
            state.save()                              # ворота закрыты — стоим на месте честно
            return state
        self.run_current(state, human_note=human_note)
        # режим «само»: гоним дальше, пока не упрёмся в паузу/воздержание/финал
        while not state.is_done() and not state.awaiting and not state.escalated:
            to, why = self._intended(state)
            if to is None:
                break
            try:
                self._guarded_advance(state, to, why)
            except GateBlocked:
                break
            self.run_current(state)
        state.save()
        return state

    # ── полный автопрогон из стартовой точки (ask_between=False) ────────────
    def run_all(self, state):
        while not state.is_done() and not state.awaiting and not state.escalated:
            to, why = self._intended(state)
            if to is None:
                break
            try:
                self._guarded_advance(state, to, why)
            except GateBlocked:
                break
            self.run_current(state)
        state.save()
        return state

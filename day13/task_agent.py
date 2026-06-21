"""День 13 — оркестратор поверх конечного автомата задачи.

Архитектура по разбору преподавателя (Алексей Гладков): один агент на этап со своим
system prompt; оркестратор гонит пайплайн сам, передавая результат этапа следующему;
после этапа агент спрашивает человека «передавать дальше?» — и встаёт на паузу.

Этапы на примере «составить договор»:
  research   → агент-аналитик: требования + применимые нормы;
  drafting   → агент-составитель: пишет документ по анализу (видит результат research);
  validation → агент-контролёр: проверяет документ на риски (видит требования + документ).

Главные ручки оркестратора:
  run_current(state) — выполнить работу ТЕКУЩЕГО этапа (свой промпт), записать артефакт,
                       при ask_between встать на паузу;
  approve(state)     — человек одобрил: перейти на следующий этап и сразу его выполнить
                       (и так до следующей паузы или до done);
  revise(state,note) — человек внёс правку: переделать текущий этап с учётом правки.

Переходы детерминированные («родился артефакт — поехали дальше»), кроме validation, где
вердикт контролёра решает done или назад в drafting. Это вариант, который преподаватель
назвал проще и надёжнее «оркестратора-нейронки».
"""
import os
import time

from openai import OpenAI, RateLimitError

from task_state import (DONE, DRAFTING, RESEARCH, VALIDATION, TaskState)


# system prompt на КАЖДЫЙ этап — «одна стадия, свой промпт» (по преподу).
RESEARCH_SYS = (
    "Ты юрист-аналитик. По задаче пользователя кратко собери: (1) что это за документ "
    "и его цель, (2) ключевые условия, которые в нём обязательно должны быть, "
    "(3) применимые нормы/риски на которые обратить внимание. 4–7 пунктов, без воды."
)
DRAFTING_SYS = (
    "Ты юрист-составитель. Напиши документ по результатам анализа. Структура с разделами, "
    "формулировки по существу. Покрой все пункты из анализа. Без вступлений и пояснений — "
    "только текст документа."
)
JUDGE_SYS = (
    "Ты юрист-контролёр. Сверь документ с требованиями анализа и найди риски/пропуски. "
    "Ответь РОВНО в формате двух строк:\n"
    "ВЕРДИКТ: OK | ДОРАБОТАТЬ\n"
    "ЗАМЕЧАНИЯ: <если ДОРАБОТАТЬ — что исправить, одной строкой; если OK — тире>\n"
    "Ставь OK только если документ полно закрывает требования анализа."
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
        )

    # ── один вызов LLM (не-стрим), с retry на лимит ────────────────────────
    def complete(self, system, user, max_tokens=900, temperature=0):
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
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
        self.ledger.append({"step": len(self.ledger) + 1, "tokens": total,
                            "cumulative": prev + total})

    # ── контекст для этапа: оркестратор передаёт результаты прошлых этапов ──
    def _context(self, state, extra=""):
        a = state.artifacts
        parts = [f"Задача: {state.goal}"]
        if a["research"]:
            parts.append(f"\nАнализ (этап research):\n{a['research']}")
        if a["draft"] and state.stage in (DRAFTING, VALIDATION):
            parts.append(f"\nТекущий документ (этап drafting):\n{a['draft']}")
        if extra:
            parts.append(f"\n{extra}")
        return "\n".join(parts)

    # ── выполнить РАБОТУ текущего этапа (свой промпт) ───────────────────────
    def run_current(self, state: TaskState, human_note=""):
        """Сделать работу текущего этапа и записать артефакт. На validation вердикт
        контролёра определяет переход. После работы (если ask_between) — пауза."""
        stage = state.stage
        extra = f"Учти правку человека: {human_note}" if human_note else ""

        if stage == RESEARCH:
            out = self.complete(RESEARCH_SYS, self._context(state, extra))
            state.record_work(out)

        elif stage == DRAFTING:
            out = self.complete(DRAFTING_SYS, self._context(state, extra))
            state.record_work(out)

        elif stage == VALIDATION:
            verdict = self.complete(JUDGE_SYS, self._context(state, extra), max_tokens=300)
            ok = self._verdict_ok(verdict)
            notes = self._notes(verdict)
            if ok:
                review = "ПРИНЯТО: документ закрывает требования. " + (
                    notes if notes and notes != "-" else "Замечаний нет.")
            elif state.revision >= self.max_revisions:
                review = "ПРИНЯТО по лимиту доработок (контролёр придирался: " + (
                    notes or "мелкие пробелы") + ")"
                ok = True
            else:
                review = "НА ДОРАБОТКУ: " + (notes or "есть пробелы относительно анализа.")
            state.artifacts["review"] = review
            state.events.append({"kind": "work", "stage": VALIDATION, "text": review})
            # на validation пауза тоже возможна, но переход решает вердикт контролёра
            state._validation_ok = ok          # запомним для approve/auto-advance
            if state.ask_between:
                state.awaiting = True
                state.events.append({"kind": "ask", "stage": VALIDATION,
                                     "text": "Контролёр вынес вердикт. Одобри переход "
                                             "или верни на доработку."})
        state.save()
        return state

    # ── человек одобрил: перейти дальше и сразу выполнить следующий этап ────
    def approve(self, state: TaskState):
        """Снять паузу, перейти на следующий этап по рельсам и выполнить его —
        и так дальше, пока снова не упрёмся в паузу или не дойдём до done."""
        if state.is_done():
            return state
        self._advance_from(state)
        # оркестратор гонит сам до следующей паузы / финала
        while not state.is_done() and not state.awaiting:
            self.run_current(state)
            if not state.awaiting and not state.is_done():
                self._advance_from(state)
        state.save()
        return state

    def _advance_from(self, state: TaskState):
        """Куда перейти из текущего этапа (детерминированно; на validation — по вердикту)."""
        if state.stage == RESEARCH:
            state.advance(DRAFTING, reason="анализ готов")
        elif state.stage == DRAFTING:
            state.advance(VALIDATION, reason="документ готов")
        elif state.stage == VALIDATION:
            if getattr(state, "_validation_ok", False):
                state.advance(DONE, reason="проверка пройдена")
            else:
                state.advance(DRAFTING, reason="контролёр вернул на доработку")

    # ── человек внёс правку: переделать текущий этап с учётом ───────────────
    def revise(self, state: TaskState, note):
        state.note_revision(note)
        self.run_current(state, human_note=note)
        state.save()
        return state

    # ── разбор вердикта судьи ──────────────────────────────────────────────
    @staticmethod
    def _verdict_ok(verdict):
        for line in (verdict or "").splitlines():
            if line.upper().startswith("ВЕРДИКТ"):
                return "OK" in line.upper() and "ДОРАБОТ" not in line.upper()
        return False

    @staticmethod
    def _notes(verdict):
        for line in (verdict or "").splitlines():
            if line.upper().startswith("ЗАМЕЧАНИЯ"):
                return line.split(":", 1)[-1].strip()
        return ""

    # ── автопрогон без остановок (когда ask_between=False) ──────────────────
    def run_all(self, state: TaskState, max_steps=10):
        steps = 0
        self.run_current(state)
        while not state.is_done() and steps < max_steps:
            if state.awaiting:                 # ask_between=True → ждём человека, выходим
                break
            self._advance_from(state)
            if not state.is_done():
                self.run_current(state)
            steps += 1
        state.save()
        return state

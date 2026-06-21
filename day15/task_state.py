"""День 15 — состояние задачи + рельсы переходов (хребет из Дня 13, расширенный под ворота).

Машина состояний осталась прежней (этапы + разрешённые переходы + единая точка смены этапа
+ персист на диск). Новое по сравнению с Днём 13 — поля, которые читают ВОРОТА (gates.py):
  • plan_approved  — план одобрен? (предусловие перехода PLANNING → EXECUTION);
  • validation     — вердикт панели валидаторов (предусловие перехода VALIDATION → DONE);
  • escalated      — панель разошлась/не уверена → ждём РЕШЕНИЯ человека (воздержание).

Разделение ответственности (важно для понимания дня):
  • task_state.py — РЕЛЬСЫ: какие стрелки вообще нарисованы (структура). advance() пускает
    переход, только если он есть в ALLOWED, иначе IllegalTransition.
  • gates.py      — ВОРОТА: выполнены ли предусловия конкретного перехода (план одобрен,
    черновик есть, вердикт PASS). Рельсы говорят «дверь нарисована», ворота — «есть пропуск».
Оркестратор НИКОГДА не зовёт advance() напрямую — только через проверку ворот (см. task_agent).
"""
import json
import os


# ── Этапы (по формулировке: planning → execution → validation → done) ───────
PLANNING = "planning"       # план работы (что и как будем делать)
EXECUTION = "execution"     # реализация: составить документ по утверждённому плану
VALIDATION = "validation"   # проверка роем валидаторов
DONE = "done"

STAGES = [PLANNING, EXECUTION, VALIDATION, DONE]

TITLE = {
    PLANNING:   "План",
    EXECUTION:  "Реализация",
    VALIDATION: "Проверка",
    DONE:       "Готово",
}
STEP_OF = {
    PLANNING:   "составить план: что должно быть в документе и на что опереться",
    EXECUTION:  "написать документ по утверждённому плану",
    VALIDATION: "прогнать документ через рой валидаторов",
    DONE:       "задача завершена",
}
ARTIFACT_OF = {PLANNING: "plan", EXECUTION: "draft", VALIDATION: "review"}

# ── РЕЛЬСЫ: какие переходы вообще существуют ─────────────────────────────────
ALLOWED = {
    PLANNING:   [EXECUTION],
    EXECUTION:  [VALIDATION],
    VALIDATION: [DONE, EXECUTION],   # PASS → done; FAIL → назад на доработку
    DONE:       [],
}


class IllegalTransition(Exception):
    """Попытка пойти по стрелке, которой нет в ALLOWED (мимо рельсов)."""


class TaskState:
    """Карточка задачи + рельсы её изменения. Сериализуется в JSON целиком."""

    def __init__(self, goal, path=None, ask_between=True):
        self.goal = goal
        self.path = path
        self.ask_between = ask_between
        self.stage = PLANNING
        self.awaiting = False              # этап выполнен, ждём решения человека (ПАУЗА)
        self.plan_approved = False         # предусловие ворот PLANNING → EXECUTION
        self.escalated = False             # панель разошлась → ждём человека (воздержание)
        self.revision = 0
        self.artifacts = {"plan": "", "draft": "", "review": ""}
        self.validation = {"decision": None, "lenses": [], "reason": ""}  # вердикт панели
        self.transitions = []              # журнал: [{from,to,reason}]
        self.events = []                   # лента для UI

    # ── свойства карточки ──────────────────────────────────────────────────
    @property
    def current_step(self):
        return STEP_OF[self.stage]

    @property
    def expected_action(self):
        if self.stage == DONE:
            return "ничего — финал"
        if self.escalated:
            return "панель разошлась — реши: принять документ или вернуть на доработку"
        if self.awaiting and self.stage == PLANNING:
            return "одобри план (откроет ворота в «Реализацию») или внеси правку"
        if self.awaiting:
            return "одобри переход дальше или внеси правку"
        return f"агент выполняет этап «{TITLE[self.stage]}»"

    # ── работа этапа пишет артефакт ────────────────────────────────────────
    def record_work(self, text, ask=True):
        key = ARTIFACT_OF.get(self.stage)
        if key:
            self.artifacts[key] = text
        self.events.append({"kind": "work", "stage": self.stage, "text": text})
        if ask and self.ask_between and self.stage != DONE:
            self.awaiting = True
            q = ("Готов план. Одобрить — и можно в «Реализацию»? Или внеси правку."
                 if self.stage == PLANNING else
                 f"Закончил этап «{TITLE[self.stage]}». Передавать дальше?")
            self.events.append({"kind": "ask", "stage": self.stage, "text": q})
        return self

    # ── ЕДИНСТВЕННАЯ точка смены этапа (только рельсы; ворота проверяет gates) ─
    def advance(self, to_stage, reason=""):
        if to_stage not in ALLOWED.get(self.stage, []):
            raise IllegalTransition(
                f"нельзя {self.stage} → {to_stage}; разрешено: {ALLOWED.get(self.stage, [])}")
        if self.stage == VALIDATION and to_stage == EXECUTION:
            self.revision += 1
        frm = self.stage
        self.stage = to_stage
        self.awaiting = False
        self.escalated = False
        self.transitions.append({"from": frm, "to": to_stage, "reason": reason})
        self.events.append({"kind": "move", "stage": to_stage,
                            "text": f"{TITLE[frm]} → {TITLE[to_stage]} ({reason})"})
        return self

    # ── ручки, на которые смотрят ворота ───────────────────────────────────
    def approve_plan(self):
        """Человек одобрил план — заправляем ворота PLANNING → EXECUTION."""
        self.plan_approved = True
        self.events.append({"kind": "approve", "stage": PLANNING,
                            "text": "Человек одобрил план — ворота в «Реализацию» открыты."})
        return self

    def set_validation(self, decision, lenses, reason):
        """Сохранить вердикт панели (decision: pass | fail | abstain)."""
        self.validation = {"decision": decision, "lenses": lenses, "reason": reason}
        return self

    def note_revision(self, human_note):
        self.revision += 1
        self.awaiting = False
        self.events.append({"kind": "revise", "stage": self.stage,
                            "text": f"Правка от человека: {human_note}"})
        return self

    def blocked(self, to_stage, reasons):
        """Зафиксировать отбитую воротами попытку перехода (для ленты/журнала)."""
        self.events.append({"kind": "blocked", "stage": self.stage,
                            "text": f"Переход {TITLE[self.stage]} → {TITLE.get(to_stage, to_stage)} "
                                    f"отбит воротами: {reasons}"})
        return self

    def escalate(self, reason):
        self.escalated = True
        self.awaiting = True
        self.events.append({"kind": "escalate", "stage": self.stage,
                            "text": f"Воздержание панели: {reason} — нужно решение человека."})
        return self

    def is_done(self):
        return self.stage == DONE

    # ── снимок для UI ──────────────────────────────────────────────────────
    def snapshot(self):
        return {
            "goal": self.goal, "stage": self.stage, "title": TITLE[self.stage],
            "current_step": self.current_step, "expected_action": self.expected_action,
            "awaiting": self.awaiting, "escalated": self.escalated,
            "ask_between": self.ask_between, "plan_approved": self.plan_approved,
            "revision": self.revision, "next_allowed": ALLOWED.get(self.stage, []),
            "stages": STAGES, "titles": TITLE, "artifacts": self.artifacts,
            "validation": self.validation, "transitions": self.transitions, "events": self.events,
        }

    # ── персист (атомарно, как День 7) ─────────────────────────────────────
    def to_dict(self):
        return {
            "goal": self.goal, "ask_between": self.ask_between, "stage": self.stage,
            "awaiting": self.awaiting, "plan_approved": self.plan_approved,
            "escalated": self.escalated, "revision": self.revision,
            "artifacts": self.artifacts, "validation": self.validation,
            "transitions": self.transitions, "events": self.events,
        }

    def save(self):
        if not self.path:
            return self
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        return self

    @classmethod
    def load(cls, path):
        if not path or not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        st = cls(d["goal"], path=path, ask_between=d.get("ask_between", True))
        st.stage = d["stage"]
        st.awaiting = d.get("awaiting", False)
        st.plan_approved = d.get("plan_approved", False)
        st.escalated = d.get("escalated", False)
        st.revision = d.get("revision", 0)
        st.artifacts = d.get("artifacts", {"plan": "", "draft": "", "review": ""})
        st.validation = d.get("validation", {"decision": None, "lenses": [], "reason": ""})
        st.transitions = d.get("transitions", [])
        st.events = d.get("events", [])
        return st

"""День 13 — состояние задачи как конечный автомат (Task State Machine).

СЕРДЦЕ ДНЯ. Ни одного вызова LLM — чистая «карточка задачи» и правила, по которым
она меняется. Архитектура по разбору преподавателя (Алексей Гладков): оркестратор сам
гонит пайплайн по этапам, у каждого этапа свой агент со своим system prompt; после
этапа агент СПРАШИВАЕТ человека «закончил, передавать дальше?» — и тут пауза.

Три вещи, которые формализует состояние (как в задании):
  • stage           — этап задачи (research / drafting / validation / done);
  • current_step    — что конкретно делаем сейчас;
  • expected_action — какого действия ждём дальше (поработать / спросить человека / перейти).

Пауза и продолжение без повторных объяснений: после работы этапа состояние с флагом
awaiting=True атомарно ложится на диск. Человек может закрыть вкладку, вернуться через
неделю — load поднимет всё (этап, артефакты, что мы ждём его «ок»), и продолжим ровно
с той же точки, ничего не переобъясняя.
"""
import json
import os


# ── Этапы (на примере «составить договор») ─────────────────────────────────
RESEARCH = "research"       # анализ: требования + применимые нормы
DRAFTING = "drafting"       # составление: написать документ по анализу
VALIDATION = "validation"   # проверка: риски/пробелы относительно требований
DONE = "done"

STAGES = [RESEARCH, DRAFTING, VALIDATION, DONE]

# Человекочитаемые подписи для UI.
TITLE = {
    RESEARCH:   "Анализ",
    DRAFTING:   "Составление",
    VALIDATION: "Проверка",
    DONE:       "Готово",
}
STEP_OF = {
    RESEARCH:   "собрать требования и применимые нормы",
    DRAFTING:   "написать документ по результатам анализа",
    VALIDATION: "проверить документ на риски и пробелы",
    DONE:       "задача завершена",
}
# В какую графу артефактов пишет этап.
ARTIFACT_OF = {RESEARCH: "research", DRAFTING: "draft", VALIDATION: "review"}

# ── РЕЛЬСЫ: какие переходы разрешены ────────────────────────────────────────
# Функция перехода автомата. Агент не может прыгнуть мимо стрелки: из validation
# можно либо в done (проверка чистая), либо назад в drafting (нашли дыру).
ALLOWED = {
    RESEARCH:   [DRAFTING],
    DRAFTING:   [VALIDATION],
    VALIDATION: [DONE, DRAFTING],
    DONE:       [],
}


class IllegalTransition(Exception):
    """Попытка пойти по стрелке, которой нет в ALLOWED."""


class TaskState:
    """Карточка задачи + правила её изменения. Сериализуется в JSON целиком."""

    def __init__(self, goal, path=None, ask_between=True):
        self.goal = goal
        self.path = path
        self.ask_between = ask_between     # спрашивать человека между этапами? (флаг препода)
        self.stage = RESEARCH
        self.awaiting = False             # этап выполнен, ждём решения человека (= ПАУЗА)
        self.revision = 0                 # сколько правок внёс человек/контролёр
        self.artifacts = {"research": "", "draft": "", "review": ""}
        self.transitions = []             # журнал: [{from,to,reason}]
        self.events = []                  # лента для UI: [{kind,stage,text}]

    # ── свойства карточки ──────────────────────────────────────────────────
    @property
    def current_step(self):
        return STEP_OF[self.stage]

    @property
    def expected_action(self):
        if self.stage == DONE:
            return "ничего — финал"
        if self.awaiting:
            return "ждём человека: одобрить переход или внести правку"
        return f"агент выполняет этап «{TITLE[self.stage]}»"

    # ── работа этапа записывает артефакт и (если надо) встаёт на паузу ──────
    def record_work(self, text):
        """Этап отработал: положить результат в нужную графу. Если включён
        ask_between — встаём на паузу и ждём человека (awaiting=True)."""
        key = ARTIFACT_OF.get(self.stage)
        if key:
            self.artifacts[key] = text
        self.events.append({"kind": "work", "stage": self.stage, "text": text})
        if self.ask_between and self.stage != DONE:
            self.awaiting = True
            self.events.append({"kind": "ask", "stage": self.stage,
                                "text": f"Закончил этап «{TITLE[self.stage]}». "
                                        f"Передавать дальше? Одобри или внеси правку."})
        return self

    # ── единственная точка смены этапа ─────────────────────────────────────
    def advance(self, to_stage, reason=""):
        """Перейти на другой этап. ЕДИНСТВЕННОЕ место смены stage → состояние
        на диске всегда честное. Снимает паузу (awaiting=False)."""
        if to_stage not in ALLOWED.get(self.stage, []):
            raise IllegalTransition(
                f"нельзя {self.stage} → {to_stage}; разрешено: {ALLOWED.get(self.stage, [])}")
        if self.stage == VALIDATION and to_stage == DRAFTING:
            self.revision += 1
        frm = self.stage
        self.stage = to_stage
        self.awaiting = False
        self.transitions.append({"from": frm, "to": to_stage, "reason": reason})
        self.events.append({"kind": "move", "stage": to_stage,
                            "text": f"{TITLE[frm]} → {TITLE[to_stage]} ({reason})"})
        return self

    def note_revision(self, human_note):
        """Человек внёс правку на паузе: запомнить, снять паузу (этап переделают)."""
        self.revision += 1
        self.awaiting = False
        self.events.append({"kind": "revise", "stage": self.stage,
                            "text": f"Правка от человека: {human_note}"})
        return self

    def is_done(self):
        return self.stage == DONE

    # ── снимок для UI ──────────────────────────────────────────────────────
    def snapshot(self):
        return {
            "goal": self.goal,
            "stage": self.stage,
            "title": TITLE[self.stage],
            "current_step": self.current_step,
            "expected_action": self.expected_action,
            "awaiting": self.awaiting,
            "ask_between": self.ask_between,
            "revision": self.revision,
            "next_allowed": ALLOWED.get(self.stage, []),
            "stages": STAGES,
            "titles": TITLE,
            "artifacts": self.artifacts,
            "transitions": self.transitions,
            "events": self.events,
        }

    # ── персист (атомарно, как День 7) ─────────────────────────────────────
    def to_dict(self):
        return {
            "goal": self.goal, "ask_between": self.ask_between, "stage": self.stage,
            "awaiting": self.awaiting, "revision": self.revision,
            "artifacts": self.artifacts, "transitions": self.transitions,
            "events": self.events,
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
        st.revision = d.get("revision", 0)
        st.artifacts = d.get("artifacts", {"research": "", "draft": "", "review": ""})
        st.transitions = d.get("transitions", [])
        st.events = d.get("events", [])
        return st

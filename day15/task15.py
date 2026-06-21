"""День 15 — CLI к ассистенту с контролируемым жизненным циклом задачи.

Команды:
  <текст>            поручить задачу (старт: этап «План»)
  /approve          одобрить текущую паузу (план / переход / финал)
  /revise <текст>   внести правку на текущем этапе
  /accept           на воздержании панели — ПРИНЯТЬ документ (в «Готово»)
  /rework           на воздержании панели — вернуть на доработку
  /try <stage>      ПОПРОБОВАТЬ переход в stage (planning/execution/validation/done) —
                    покажет, открыт ли (рельсы + ворота), НЕ меняя состояние
  /state            показать карточку состояния и ворота на разрешённые переходы
  /auto             переключить режим «спрашивать между этапами»
  /reset            сбросить
  /quit
"""
import os

from dotenv import load_dotenv

from gates import check_gate
from task_agent import TaskAgent
from task_state import ALLOWED, STAGES, TITLE, TaskState

load_dotenv()
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")


def show_state(st):
    print(f"\n  этап: {st.stage} ({TITLE[st.stage]}) | шаг: {st.current_step}")
    print(f"  ждём: {st.expected_action}")
    if st.validation.get("decision"):
        print(f"  вердикт панели: {st.validation['decision']} — {st.validation['reason']}")
    for to in ALLOWED.get(st.stage, []):
        g = check_gate(st, to)
        mark = "ОТКРЫТО" if g["passed"] else "ЗАКРЫТО"
        conds = ", ".join(f"{c['reason']}{'' if c['ok'] else ' ✗'}" for c in g["checks"])
        print(f"  ворота → {TITLE[to]}: {mark} ({conds})")
    print()


def main():
    agent = TaskAgent()
    st = TaskState.load(STATE_FILE)
    if st:
        print("Поднял состояние с диска (resume).")
        show_state(st)
    else:
        print("Поручи задачу (напр.: составить договор аренды квартиры). /quit — выход.")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        elif line == "/reset":
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            agent.ledger = []
            st = None
            print("Сброшено.")
        elif line == "/state":
            show_state(st) if st else print("Задачи нет.")
        elif line == "/auto":
            if st:
                st.ask_between = not st.ask_between
                st.save()
                print("ask_between =", st.ask_between)
        elif line.startswith("/try"):
            if not st:
                print("Задачи нет."); continue
            to = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
            if to not in STAGES:
                print("укажи этап:", "/".join(STAGES)); continue
            r = agent.try_jump(st, to)
            if r["ok"]:
                print(f"  → {TITLE[to]}: ОТКРЫТО (рельсы и ворота пройдены)")
            elif r["kind"] == "off_rails":
                print(f"  → {TITLE[to]}: МИМО РЕЛЬСОВ — {r['reason']}; разрешено: "
                      f"{[TITLE[s] for s in r['allowed']]}")
            else:
                print(f"  → {TITLE[to]}: ВОРОТА ЗАКРЫТЫ — {r['reason']}")
        elif line == "/approve":
            if st:
                agent.approve(st); show_state(st)
        elif line == "/accept":
            if st:
                agent.resolve(st, accept=True); show_state(st)
        elif line == "/rework":
            if st:
                agent.resolve(st, accept=False); show_state(st)
        elif line.startswith("/revise"):
            if st:
                note = line.split(maxsplit=1)[1] if len(line.split()) > 1 else ""
                agent.revise(st, note); show_state(st)
        else:
            # поручить новую задачу
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            agent.ledger = []
            st = TaskState(line, path=STATE_FILE, ask_between=True)
            st.save()
            agent.run_current(st)
            show_state(st)


if __name__ == "__main__":
    main()

"""День 13 — CLI: агент с формализованным состоянием задачи (конечный автомат).

Главное, что показывает этот файл, — ПАУЗА и ПРОДОЛЖЕНИЕ. Состояние задачи лежит в
файле state.json. Запусти, сделай пару шагов, выйди (/quit). Запусти снова с тем же
файлом — агент поднимет состояние с диска и продолжит с того же этапа, не переспрашивая
задачу и не перепланируя. Это и есть «продолжение без повторных объяснений».

Запуск:
  python task13.py "Написать короткую статью про пользу сна"   # новая задача
  python task13.py                                              # продолжить сохранённую

Команды в интерактиве:
  /step    — один шаг автомата (сделать работу этапа и перейти дальше)
  /run     — гнать до конца (done)
  /state   — карточка состояния (этап / шаг / ожидаемое действие)
  /plan    /draft   — показать накопленные артефакты
  /log     — журнал переходов
  /reset   — стереть состояние и начать заново (нужна новая задача)
  /quit    — выйти (состояние уже на диске — это и есть пауза)
"""
import sys

from dotenv import load_dotenv

from task_agent import TaskAgent
from task_state import STAGES, TaskState

load_dotenv()

STATE_FILE = "state.json"


def show_state(state):
    s = state.snapshot()
    # рельсы автомата с подсветкой текущего этапа
    rail = " → ".join(f"[{st}]" if st == s["stage"] else st for st in STAGES)
    print(f"\n  {rail}")
    print(f"  этап:             {s['stage']}")
    print(f"  текущий шаг:      {s['current_step']}")
    print(f"  ожидаемое дейст.: {s['expected_action']}")
    print(f"  доработок:        {s['revision']}")
    print(f"  есть артефакты:   " +
          ", ".join(k for k, v in s["has"].items() if v) or "  (пока пусто)")
    print(f"  можно перейти в:  {s['next_allowed'] or '— (финал)'}\n")


def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else None

    state = TaskState.load(STATE_FILE)
    if state and goal and goal != state.goal:
        print(f"На диске есть незавершённая задача: «{state.goal}»")
        print("Продолжаю её. Чтобы начать новую — /reset, потом перезапусти с новой задачей.")
    elif state:
        print(f"↩  Поднял состояние с диска. Продолжаю с этапа «{state.stage}», "
              f"ничего не переобъясняю.")
    elif goal:
        state = TaskState(goal, path=STATE_FILE)
        state.save()
        print(f"Новая задача: «{goal}»")
    else:
        print("Нет сохранённой задачи. Запусти с текстом задачи:\n"
              '  python task13.py "твоя задача"')
        return

    agent = TaskAgent()
    show_state(state)
    print("Команды: /step /run /state /plan /draft /log /reset /quit")

    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(пауза — состояние сохранено на диск)")
            break

        if cmd == "/quit":
            print("(пауза — состояние сохранено на диск, продолжишь при следующем запуске)")
            break
        elif cmd == "/step":
            if state.is_done():
                print("Задача уже завершена. /draft — посмотреть результат, /reset — заново.")
                continue
            rep = agent.step(state)
            print(f"\n· {rep['did']}", f"→ вердикт {rep.get('verdict')}"
                  if rep.get("verdict") else "")
            if rep.get("text"):
                print("  " + rep["text"].strip().replace("\n", "\n  ")[:600])
            show_state(state)
        elif cmd == "/run":
            agent.run(state, on_step=lambda r: print(f"· {r['did']} → {r['stage']}"))
            show_state(state)
            if state.is_done():
                print("Готово. /draft — результат.")
        elif cmd == "/state":
            show_state(state)
        elif cmd == "/plan":
            print("\n" + (state.artifacts["plan"] or "(плана ещё нет)") + "\n")
        elif cmd == "/draft":
            print("\n" + (state.artifacts["draft"] or "(черновика ещё нет)") + "\n")
        elif cmd == "/log":
            print()
            for t in state.transitions:
                print(f"  {t['from']:>10} → {t['to']:<10}  ({t['reason']})")
            print()
        elif cmd == "/reset":
            import os
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            print("Состояние стёрто. Перезапусти с новой задачей.")
            break
        else:
            print("Команды: /step /run /state /plan /draft /log /reset /quit")


if __name__ == "__main__":
    main()

"""День 11 — CLI: ассистент с явной моделью памяти из трёх слоёв.

Запуск:
    .venv/bin/python task11.py            # память живёт в файлах (переживёт перезапуск)
    .venv/bin/python task11.py --fresh    # с чистого листа, без файлов

После каждой реплики видно ТРАССУ роутера: что он положил в рабочую, что в
долговременную, а что не сохранил. Команды:
    /memory      — показать все три слоя;
    /route       — решение роутера на прошлой реплике (что и куда);
    /longterm    — долговременная (профиль);  /working — рабочая (задача);
    /view        — что РЕАЛЬНО ушло в модель на прошлом ходу;
    /noprofile <вопрос> — задать вопрос БЕЗ долговременной памяти (увидеть влияние);
    /newtask     — новая задача: чистит рабочую и диалог, профиль оставляет;
    /demo        — прогон сценария: что в какой слой + влияние профиля на ответ;
    /clear       — стереть всю память;  /exit — выход.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from agent import Agent
from demos import run_influence, run_layers, run_new_task

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")

SYSTEM_PROMPT = ("Ты — ассистент-помощник разработчика. Отвечай по-русски, по делу. "
                 "Учитывай профиль пользователя и данные задачи, если они даны.")


def show_card(title, text):
    print(f"\n  ── {title} ──")
    print("  " + (text.replace("\n", "\n  ") if text else "[пусто]") + "\n")


def show_memory(agent):
    v = agent.memory.view()
    print("\n  ╔═ ПАМЯТЬ АССИСТЕНТА ═══════════════════════════")
    s = v["short"]
    print(f"  ║ КРАТКОСРОЧНАЯ (диалог): {len(s['messages'])} реплик, "
          f"окно последних {s['keep_last']} (за окном — {s['dropped']})")
    print(f"  ║ РАБОЧАЯ (задача): {len(v['working']['fields'])} полей")
    for k, val in v["working"]["fields"]:
        print(f"  ║    • {k}: {val}" if k else f"  ║    • {val}")
    print(f"  ║ ДОЛГОВРЕМЕННАЯ (профиль): {len(v['longterm']['fields'])} полей")
    for k, val in v["longterm"]["fields"]:
        print(f"  ║    • {k}: {val}" if k else f"  ║    • {val}")
    print("  ╚═══════════════════════════════════════════════\n")


def show_route(agent):
    routes = agent.memory.routes
    if not routes:
        print("  [роутер ещё не отрабатывал]")
        return
    t = routes[-1]
    print(f"\n  ── РОУТЕР на реплике «{t['message']}» ──")
    if t["saved_nothing"]:
        print("  → ничего не сохранил (проходная реплика)\n")
        return
    if t["to_working"]:
        print("  → в РАБОЧУЮ (задача): " + " · ".join(t["to_working"]))
    if t["to_longterm"]:
        print("  → в ДОЛГОВРЕМЕННУЮ (профиль): " + " · ".join(t["to_longterm"]))
    print()


def route_line(trace):
    """Короткая трасса под ответом — куда роутер положил факт из этой реплики."""
    if trace["saved_nothing"]:
        return "  └ роутер: ничего не сохранил (проходная реплика)"
    bits = []
    if trace["to_working"]:
        bits.append("в рабочую: " + "; ".join(trace["to_working"]))
    if trace["to_longterm"]:
        bits.append("в долговременную: " + "; ".join(trace["to_longterm"]))
    return "  └ роутер → " + "  |  ".join(bits)


def cmd_demo(agent):
    print("\n[Демо] Прогоняю сценарий (реальные вызовы) — кладу факты по слоям…\n")
    layers = run_layers(agent)
    for st in layers["steps"]:
        where = []
        if st["to_working"]:
            where.append("рабочая ← " + "; ".join(st["to_working"]))
        if st["to_longterm"]:
            where.append("долговременная ← " + "; ".join(st["to_longterm"]))
        got = " | ".join(where) if where else "ничего не сохранено"
        print(f"  «{st['message'][:55]}»")
        print(f"     ожидали: {st['expected']}   →   роутер: {got}")
    show_card("РАБОЧАЯ (задача)", layers["working"])
    show_card("ДОЛГОВРЕМЕННАЯ (профиль)", layers["longterm"])

    print("[Демо] Новая сессия того же пользователя (диалог пуст), один вопрос — "
          "два ответа: с профилем и без (реальные вызовы)…\n")
    inf = run_influence(agent)
    print(f"  Вопрос: {inf['question']}")
    print(f"  В профиле: {inf['longterm_card'].replace(chr(10), ' · ')}\n")
    print(f"  ── С долговременной памятью ── [{inf['len_with']} симв., "
          f"таблица: {'да' if inf['table_with'] else 'нет'}]")
    print("  " + inf["with_longterm"][:280].replace("\n", "\n  ") + "\n")
    print(f"  ── БЕЗ долговременной памяти ── [{inf['len_without']} симв., "
          f"таблица: {'да' if inf['table_without'] else 'нет'}]")
    print("  " + inf["without_longterm"][:280].replace("\n", "\n  ") + "\n")
    print("  → Тот же вопрос, разные ответы: с профилем — коротко и по делу (как "
          "просил пользователь); без профиля модель не знает его привычек и выкатывает "
          "длинный ответ. Это и есть влияние долговременного слоя.\n")

    nt = run_new_task(agent)
    print("[Демо] /newtask — новая задача:")
    print(f"     рабочая очищена: {'да' if nt['working_cleared'] else 'нет'}  |  "
          f"профиль сохранён: {'да' if nt['longterm_kept'] else 'нет'}")
    print("  → задача уехала в архив, профиль человека остался в силе.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="не использовать файлы памяти")
    ap.add_argument("--window", type=int, default=6, help="окно краткосрочной памяти")
    args = ap.parse_args()

    paths = None if args.fresh else {
        "dialog": os.path.join(HERE, "mem_dialog.json"),
        "working": os.path.join(HERE, "mem_working.txt"),
        "longterm": os.path.join(HERE, "mem_longterm.txt"),
    }
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, short_keep=args.window, paths=paths)

    print(f"[модель={MODEL}  |  окно={args.window}  |  "
          f"память: {'в файлах' if paths else 'в памяти процесса'}]")
    print("[команды: /memory /route /longterm /working /view /noprofile <q> "
          "/newtask /demo /clear /exit]")
    if paths and (agent.memory.longterm.text or agent.memory.working.text):
        print("[подняли память с диска]")
        show_memory(agent)

    while True:
        try:
            text = input("\nты> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[выход]")
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/clear":
            agent.reset()
            print("[вся память стёрта]")
            continue
        if text == "/memory":
            show_memory(agent)
            continue
        if text == "/route":
            show_route(agent)
            continue
        if text == "/longterm":
            show_card("ДОЛГОВРЕМЕННАЯ (профиль)", agent.memory.longterm.text)
            continue
        if text == "/working":
            show_card("РАБОЧАЯ (задача)", agent.memory.working.text)
            continue
        if text == "/view":
            print("\n  ── ЧТО УШЛО В МОДЕЛЬ (прошлый ход) ──")
            for m in agent.last_sent or []:
                print(f"  [{m['role']}] {m['content'][:90]}")
            print()
            continue
        if text == "/newtask":
            agent.memory.new_task()
            print("[новая задача: рабочая и диалог очищены, профиль сохранён]")
            continue
        if text.startswith("/noprofile"):
            q = text[len("/noprofile"):].strip()
            if not q:
                print("[использование: /noprofile <вопрос>]")
                continue
            print(f"{agent.name} (без профиля)> ", end="", flush=True)
            agent.send(q, printer=lambda t: print(t, end="", flush=True), use_longterm=False)
            print("\n" + route_line(agent.memory.routes[-1]))
            continue
        if text == "/demo":
            cmd_demo(agent)
            continue

        print(f"{agent.name}> ", end="", flush=True)
        agent.send(text, printer=lambda t: print(t, end="", flush=True))
        print()
        print(route_line(agent.memory.routes[-1]))


if __name__ == "__main__":
    sys.exit(main())

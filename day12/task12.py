"""День 12 — CLI: ассистент с персонализацией поверх модели памяти.

Запуск:
    .venv/bin/python task12.py            # память живёт в файлах (переживёт перезапуск)
    .venv/bin/python task12.py --fresh    # с чистого листа, без файлов

Профиль кормится двумя путями: ты задаёшь предпочтение явно (/pref) ИЛИ ассистент
сам замечает его по ходу диалога (роутер). Профиль идёт в КАЖДЫЙ запрос. Команды:
    /profile     — показать профиль: заданное тобой + замеченное автоматически;
    /pref <текст>— задать предпочтение явно («пиши кратко, я юрист»);
    /memory      — показать все слои (диалог / рабочая / профиль);
    /route       — что роутер заметил на прошлой реплике;
    /view        — что РЕАЛЬНО ушло в модель на прошлом ходу;
    /noprofile <вопрос> — тот же вопрос БЕЗ профиля (увидеть влияние персонализации);
    /newtask     — новая задача: чистит рабочую и диалог, профиль оставляет;
    /demo        — два профиля на одном вопросе + автонаполнение + новая задача;
    /clear       — стереть всю память;  /exit — выход.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from agent import Agent
from demos import run_auto_notice, run_new_task, run_two_profiles

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")

SYSTEM_PROMPT = ("Ты — ассистент-помощник. Отвечай по-русски. Строго соблюдай профиль "
                 "пользователя (стиль, формат, ограничения), если он задан.")


def show_card(title, text):
    print(f"\n  ── {title} ──")
    print("  " + (text.replace("\n", "\n  ") if text else "[пусто]") + "\n")


def show_profile(agent):
    p = agent.memory.profile.view()
    print("\n  ╔═ ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ════════════════════════")
    print(f"  ║ ЗАДАНО ТОБОЙ ({len(p['stated']['fields'])} полей):")
    for k, val in p["stated"]["fields"]:
        print(f"  ║    • {k}: {val}" if k else f"  ║    • {val}")
    if not p["stated"]["fields"]:
        print("  ║    [пусто — задай через /pref]")
    print(f"  ║ ЗАМЕЧЕНО АВТОМАТИЧЕСКИ ({len(p['noticed']['fields'])} полей):")
    for k, val in p["noticed"]["fields"]:
        print(f"  ║    • {k}: {val}" if k else f"  ║    • {val}")
    if not p["noticed"]["fields"]:
        print("  ║    [пока ничего не замечено]")
    print("  ╚═══════════════════════════════════════════════\n")


def show_memory(agent):
    v = agent.memory.view()
    s = v["short"]
    print("\n  ╔═ ПАМЯТЬ АССИСТЕНТА ═══════════════════════════")
    print(f"  ║ КРАТКОСРОЧНАЯ (диалог): {len(s['messages'])} реплик, "
          f"окно последних {s['keep_last']} (за окном — {s['dropped']})")
    print(f"  ║ РАБОЧАЯ (задача): {len(v['working']['fields'])} полей")
    for k, val in v["working"]["fields"]:
        print(f"  ║    • {k}: {val}" if k else f"  ║    • {val}")
    pr = v["profile"]
    print(f"  ║ ПРОФИЛЬ — задано: {len(pr['stated']['fields'])}, "
          f"замечено: {len(pr['noticed']['fields'])} (см. /profile)")
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
    if t["to_noticed"]:
        print("  → в ПРОФИЛЬ (замечено): " + " · ".join(t["to_noticed"]))
    print()


def route_line(trace):
    if trace["saved_nothing"]:
        return "  └ ассистент ничего не заметил (проходная реплика)"
    bits = []
    if trace["to_working"]:
        bits.append("в рабочую: " + "; ".join(trace["to_working"]))
    if trace["to_noticed"]:
        bits.append("в профиль (заметил сам): " + "; ".join(trace["to_noticed"]))
    return "  └ " + "  |  ".join(bits)


def cmd_demo(agent):
    print("\n[Демо 1] Один вопрос — два профиля (реальные вызовы)…\n")
    two = run_two_profiles(agent)
    print(f"  Вопрос: {two['question']}\n")
    for key in ("profile_a", "profile_b"):
        d = two[key]
        print(f"  ── Профиль «{d['name']}» ── [{d['len']} симв., "
              f"код: {'да' if d['has_code'] else 'нет'}]")
        print("  карточка: " + d["card"].replace("\n", " · "))
        print("  " + d["answer"][:300].replace("\n", "\n  ") + "\n")
    print("  → Один вопрос, два ответа: юристу — простыми словами без кода, "
          "разработчику — кратко с примером на Python. Это и есть персонализация.\n")

    print("[Демо 2] Обычный диалог без команд «запомни» — что ассистент заметил сам…\n")
    auto = run_auto_notice(agent)
    for st in auto["steps"]:
        got = "; ".join(st["to_noticed"]) if st["to_noticed"] else "(ничего)"
        print(f"  «{st['message'][:55]}»  →  заметил: {got}")
    show_card("ПРОФИЛЬ (замечено автоматически)", auto["noticed"])
    print("  → Пользователь нигде не говорил «сохрани это», а профиль наполнился сам.\n")

    nt = run_new_task(agent)
    print("[Демо 3] /newtask — новая задача:")
    print(f"     рабочая очищена: {'да' if nt['working_cleared'] else 'нет'}  |  "
          f"профиль сохранён: {'да' if nt['profile_kept'] else 'нет'}")
    print("  → задача уехала в архив, профиль человека остался в силе.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="не использовать файлы памяти")
    ap.add_argument("--window", type=int, default=6, help="окно краткосрочной памяти")
    args = ap.parse_args()

    paths = None if args.fresh else {
        "dialog": os.path.join(HERE, "mem_dialog.json"),
        "working": os.path.join(HERE, "mem_working.txt"),
        "stated": os.path.join(HERE, "mem_profile_stated.txt"),
        "noticed": os.path.join(HERE, "mem_profile_noticed.txt"),
    }
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, short_keep=args.window, paths=paths)

    print(f"[модель={MODEL}  |  окно={args.window}  |  "
          f"память: {'в файлах' if paths else 'в памяти процесса'}]")
    print("[команды: /profile /pref <текст> /memory /route /view /noprofile <q> "
          "/newtask /demo /clear /exit]")
    if paths and not agent.memory.profile.is_empty():
        print("[подняли профиль с диска]")
        show_profile(agent)

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
        if text == "/profile":
            show_profile(agent)
            continue
        if text == "/memory":
            show_memory(agent)
            continue
        if text == "/route":
            show_route(agent)
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
        if text.startswith("/pref"):
            pref = text[len("/pref"):].strip()
            if not pref:
                print("[использование: /pref <как ты хочешь получать ответы>]")
                continue
            res = agent.memory.state_preference(pref)
            print("[предпочтение учтено] добавлено/изменено: "
                  + ("; ".join(res["added"]) if res["added"] else "(без изменений)"))
            show_card("ПРОФИЛЬ (задано тобой)", res["after"])
            continue
        if text.startswith("/noprofile"):
            q = text[len("/noprofile"):].strip()
            if not q:
                print("[использование: /noprofile <вопрос>]")
                continue
            print(f"{agent.name} (без профиля)> ", end="", flush=True)
            agent.send(q, printer=lambda t: print(t, end="", flush=True), use_profile=False)
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

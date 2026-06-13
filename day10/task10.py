"""День 10 — CLI: агент с тремя переключаемыми стратегиями контекста.

Запуск:
    .venv/bin/python task10.py                 # режим «окно» (по умолчанию)
    .venv/bin/python task10.py --mode facts --window 6

Команды (переключатель стратегий — это и есть суть задания):
    /mode window|facts|branch — сменить стратегию на лету;
    /window N                 — размер окна (последние N сообщений) для window/facts;
    /facts                    — показать карточку фактов;
    /view                     — что РЕАЛЬНО ушло в модель на прошлом ходу;
  ветки (в режиме branch):
    /checkpoint [имя]         — поставить закладку (заморозить общий ствол);
    /fork <имя>               — создать ветку от закладки;
    /switch <имя>             — переключиться на ветку;
    /branches                 — список веток и активная;
    /compare                  — окно vs facts на сценарии сбора ТЗ (реальные вызовы);
    /clear                    — стереть всё;  /exit — выход.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from agent import Agent
from demos import run_compare
from strategies import Branching, SlidingWindow, StickyFacts

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")


def meter(agent, mode):
    """Счётчик последнего хода: режим + что в запросе."""
    rec = agent.ledger[-1] if agent.ledger else None
    inp = rec["usage"]["prompt_tokens"] if rec else "—"
    sent = agent.last_sent or []
    body = [m for m in sent if m["role"] != "system"]
    line = f"  ┌─ режим: {mode}  |  вход (в модель): {inp} ток.  |  в запросе реплик: {len(body)}"
    if mode == "facts":
        fview = agent.context.view()
        line += f"\n  └ карточка: {fview['facts'].replace(chr(10), ' · ') or '[пусто]'}"
    elif mode == "branch":
        bview = agent.branches.view()
        line += (f"\n  └ ветка: {bview['active']}  |  ствол: {bview['trunk_len']}  "
                 f"|  ветки: {bview['branches']}")
    else:
        line += f"\n  └ окно: последние {agent.context.view()['keep_last']} сообщений (старее — отброшено)"
    return line


def cmd_compare(agent):
    print("[Сравнение] гоняю сбор ТЗ через окно и facts (реальные вызовы)…\n")
    res = run_compare(agent, filler_turns=8, keep_last=6)
    print(f"  Спрятанный факт: бюджет {res['budget']} ₽, дедлайн {res['deadline']}\n")
    labels = {"window": "Окно", "facts": "Facts (карточка)"}
    for key in ("window", "facts"):
        h = res["heroes"][key]
        mark = "✓ факт сохранён" if h["fact_recalled"] else "✗ факт потерян"
        print(f"  ── {labels[key]}  [{mark}]")
        print(f"     вход финала: {h['final_input_real']} ток.  |  цена карточки: {h['extract_tokens_real']} ток.")
        print(f"     ответ: {h['reply'][:160]}")
        if h["facts"]:
            print(f"     карточка: {h['facts'].replace(chr(10), ' · ')}")
        print()
    print("  → Окно дёшево, но теряет ранний факт; facts держит его ценой вызовов на карточку.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["window", "facts", "branch"], default="window")
    ap.add_argument("--window", type=int, default=6, help="окно: последние N сообщений")
    args = ap.parse_args()

    agent = Agent(system_prompt="Ты — лаконичный ассистент, помогаешь собрать ТЗ. По-русски, по делу.",
                  model=MODEL, name="Агент")
    # три персистентные стратегии (карточка/ствол не теряются при переключении)
    strategies = {
        "window": SlidingWindow(keep_last=args.window),
        "facts": StickyFacts(agent.make_extractor(), keep_last=args.window),
        "branch": Branching(),
    }
    mode = args.mode
    agent.set_context(strategies[mode])

    print(f"[режим: {mode}  |  окно={args.window}  |  модель={MODEL}]")
    print("[команды: /mode window|facts|branch  /window N  /facts  /view  /compare  /clear  /exit]")
    if mode == "branch":
        print("[ветки: /checkpoint [имя]  /fork <имя>  /switch <имя>  /branches]")

    while True:
        try:
            text = input(f"\nты [{mode}]> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[выход]")
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/clear":
            agent.reset()
            strategies["facts"] = StickyFacts(agent.make_extractor(), keep_last=args.window)
            strategies["branch"] = Branching()
            agent.set_context(strategies[mode])
            print("[всё стёрто]")
            continue
        if text.startswith("/mode"):
            parts = text.split()
            if len(parts) > 1 and parts[1] in strategies:
                mode = parts[1]
                agent.set_context(strategies[mode])
                print(f"[режим → {mode}]")
            else:
                print("[/mode window|facts|branch]")
            continue
        if text.startswith("/window"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                args.window = int(parts[1])
                strategies["window"].keep_last = args.window
                strategies["facts"].keep_last = args.window
                print(f"[окно → {args.window}]")
            continue
        if text == "/facts":
            print("\n  ── КАРТОЧКА ФАКТОВ ──")
            print("  " + (strategies["facts"].facts.replace("\n", "\n  ") or "[пусто]") + "\n")
            continue
        if text == "/view":
            print("\n  ── ЧТО УШЛО В МОДЕЛЬ (прошлый ход) ──")
            for m in agent.last_sent or []:
                print(f"  [{m['role']}] {m['content'][:90]}")
            print()
            continue
        if text == "/compare":
            cmd_compare(agent)
            continue
        # ── команды веток ──
        if text.startswith("/checkpoint"):
            if mode != "branch":
                print("[ветки доступны в режиме branch: /mode branch]"); continue
            name = text.split(maxsplit=1)[1] if len(text.split()) > 1 else "checkpoint"
            at = agent.branches.checkpoint(name)
            print(f"[закладка «{name}» — ствол заморожен на {at} сообщ.]")
            continue
        if text.startswith("/fork"):
            if mode != "branch":
                print("[/mode branch]"); continue
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                agent.branches.fork(parts[1]); print(f"[ветка «{parts[1]}» создана от закладки]")
            continue
        if text.startswith("/switch"):
            if mode != "branch":
                print("[/mode branch]"); continue
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                a = agent.branches.switch(parts[1]); print(f"[активна ветка «{a}»]")
            continue
        if text == "/branches":
            if mode != "branch":
                print("[/mode branch]"); continue
            v = agent.branches.view()
            print(f"  активная: {v['active']}  |  ствол: {v['trunk_len']}  |  ветки: {v['branches']}")
            continue

        print(f"{agent.name}> ", end="", flush=True)
        agent.send(text, printer=lambda t: print(t, end="", flush=True))
        print()
        print(meter(agent, mode))


if __name__ == "__main__":
    sys.exit(main())

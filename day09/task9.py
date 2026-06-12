"""День 9 — CLI: агент со сжатием истории.

Запуск:
    .venv/bin/python task9.py                 # сжатие включено (по умолчанию)
    .venv/bin/python task9.py --no-compress   # начать без сжатия (полная история)
    .venv/bin/python task9.py --keep 4 --trigger 10

После каждого ответа печатается счётчик: режим, вход (токены), что в копилке/окне.
Команды:
    /compress on|off — переключить сжатие на лету;
    /summary         — показать копилку (что сейчас в выжимке) и состояние окна;
    /compare         — прогнать сравнение без/со сжатия на скриптовом диалоге;
    /clear           — стереть память и копилку;  /exit — выход.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from agent import Agent
from compress import NoCompression, RollingSummary
from demos import run_compare
from memory import JsonMemory

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")


def fmt_meter(agent, compress, roll):
    """Счётчик последнего хода: режим + вход + сводка по отсекам."""
    rec = agent.ledger[-1] if agent.ledger else None
    inp = rec["usage"]["prompt_tokens"] if rec else "—"
    mode = "со сжатием" if compress else "без сжатия"
    v = roll.view()
    line = (f"  ┌─ режим: {mode}  |  вход (в модель): {inp} ток.\n"
            f"  │ всего в истории: {len(agent.history)} сообщ.")
    if compress:
        line += (f"  |  свёрнуто в копилку: {v['folded']}  |  сжатий было: {v['summarizations']}\n"
                 f"  └ окно дословно: последние {v['keep_last']} реплик")
    else:
        line += "\n  └ копилка не используется — шлём всю историю"
    return line


def cmd_summary(roll):
    v = roll.view()
    print("\n  ── КОПИЛКА (summary) ──")
    print("  " + (v["summary"] or "[пусто — ещё нечего сворачивать]"))
    print(f"\n  свёрнуто сообщений: {v['folded']}  |  сжатий: {v['summarizations']}  |  окно: {v['keep_last']} реплик\n")


def cmd_compare(agent):
    print("[Сравнение] гоняю один диалог через три режима (реальные вызовы)…\n")
    res = run_compare(agent, filler_turns=10, keep_last=4, trigger=10)
    print(f"  Спрятанный факт: {res['fact']}\n")
    for key in ("plain", "smart", "naive"):
        h = res["heroes"][key]
        mark = "✓ факт сохранён" if h["fact_recalled"] else "✗ факт потерян"
        label = {"plain": "Без сжатия", "smart": "Сжатие + guardrail", "naive": "Сжатие наивное"}[key]
        print(f"  ── {label}  [{mark}]")
        print(f"     вход финала: {h['final_input_real']} ток.  |  цена сжатия: {h['summary_tokens_real']} ток.  |  сжатий: {h['summarizations']}")
        print(f"     ответ: {h['reply'][:160]}")
        if h["summary"]:
            print(f"     копилка: {h['summary'][:160]}")
        print()
    print("  → Сжатие сохраняет факт только с guardrail; наивное теряет его при той же экономии.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compress", action="store_true", help="начать без сжатия")
    ap.add_argument("--keep", type=int, default=4, help="окно: последние N реплик дословно")
    ap.add_argument("--trigger", type=int, default=8, help="порог: при стольких несвёрнутых — сворачиваем")
    args = ap.parse_args()

    memory = JsonMemory(os.path.join(HERE, "memory.json"))
    agent = Agent(system_prompt="Ты — лаконичный ассистент. Отвечай по-русски, по делу.",
                  model=MODEL, memory=memory, name="Агент")
    roll = RollingSummary(agent.make_summarizer(), keep_last=args.keep, trigger=args.trigger)
    plain = NoCompression()
    compress = not args.no_compress

    n = len(agent.history)
    print(f"[память: загружено {n} сообщений с диска]" if n else "[память пуста]")
    print(f"[сжатие: {'ВКЛ' if compress else 'выкл'}  |  окно={args.keep}  триггер={args.trigger}]")
    print("[команды: /compress on|off  /summary  /compare  /clear  /exit]")

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
            roll = RollingSummary(agent.make_summarizer(), keep_last=args.keep, trigger=args.trigger)
            print("[память и копилка стёрты]")
            continue
        if text.startswith("/compress"):
            arg = text.split()[1] if len(text.split()) > 1 else ""
            compress = arg != "off"
            print(f"[сжатие: {'ВКЛ' if compress else 'выкл'}]")
            continue
        if text == "/summary":
            cmd_summary(roll)
            continue
        if text == "/compare":
            cmd_compare(agent)
            continue

        agent.context = roll if compress else plain
        print(f"{agent.name}> ", end="", flush=True)
        agent.send(text, printer=lambda t: print(t, end="", flush=True))
        print()
        print(fmt_meter(agent, compress, roll))


if __name__ == "__main__":
    sys.exit(main())

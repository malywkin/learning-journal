"""День 8 — CLI: агент, который считает токены и показывает, как они влияют.

Запуск:
    .venv/bin/python task8.py                 # обычный чат + счётчик токенов
    .venv/bin/python task8.py --store sqlite  # с памятью в SQLite (наследие Дня 7)

После каждого ответа печатается «счётчик токенов» этого хода. Команды:
    /cost     — сводка роста (по ходам: вход / выход / нарастающая цена);
    /overflow — Сценарий А: довести запрос до ошибки переполнения окна (400);
    /forget   — Сценарий Б: показать конфабуляцию, когда факт «отъехал» из окна;
    /clear    — стереть память (и бухгалтерию);  /exit — выход.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from agent import Agent
from demos import run_forget, run_overflow
from memory import JsonMemory, SqliteMemory

load_dotenv()
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")


def fmt_meter(rec):
    """Человеческий «счётчик токенов» по последней записи бухгалтерии."""
    u = rec["usage"]
    pct = 100 * (u["total_tokens"] or 0) / rec["window"]
    extra = []
    if u.get("reasoning_tokens"):
        extra.append(f"из них «мыслей»: {u['reasoning_tokens']}")
    if u.get("cached_tokens"):
        extra.append(f"из кэша входа: {u['cached_tokens']}")
    extra_s = ("   (" + ", ".join(extra) + ")") if extra else ""
    return (
        f"  ┌─ токены хода #{rec['turn']}\n"
        f"  │ вход (вся история): {u['prompt_tokens']:>6}   ← наша прикидка до ответа: {rec['estimate_sent']}\n"
        f"  │ выход (ответ):      {u['completion_tokens']:>6}{extra_s}\n"
        f"  │ всего:              {u['total_tokens']:>6}   | окно: {u['total_tokens']}/{rec['window']} ({pct:.2f}%)\n"
        f"  └ «как если бы» цена хода: ${rec['as_if_cost']:.6f}   | за сессию: ${rec['cumulative_cost']:.6f}"
    )


def cmd_cost(agent):
    if not agent.ledger:
        print("[пока нет ходов — бухгалтерия пуста]")
        return
    print("\n  ход | вход | выход | всего | нараст.цена")
    print("  ----+------+-------+-------+-----------")
    for r in agent.ledger:
        u = r["usage"]
        print(f"  {r['turn']:>3} | {u['prompt_tokens']:>4} | {u['completion_tokens']:>5} | "
              f"{u['total_tokens']:>5} | ${r['cumulative_cost']:.6f}")
    print("  Видно: колонка «вход» растёт каждый ход — мы шлём всю историю заново.\n")


def cmd_overflow(agent):
    print("[Сценарий А] шлю заведомо огромный промпт (≈847k токенов) в окно 131k…")
    res = run_overflow(agent)
    if res["ok"]:
        print("  неожиданно прошло без ошибки (проверь модель/окно)")
    else:
        print(f"  получили {res['error_type']}:")
        print(f"  {res['error']}")
        print("  → На нашем стеке окно НЕ обрезается молча: сервер честно отказал (400).")


def cmd_forget(agent):
    print("[Сценарий Б] сажаю факт в начало, забиваю окно, показываю три поведения…")
    res = run_forget(agent)
    print(f"\n  Спрятанный факт: {res['fact']}")
    print(f"  (узкое окно = последние {res['window_turns']} ходов; факт из него выпал)\n")
    for key in ("full", "window_ask", "window_form"):
        p = res[key]
        mark = "✓ верно" if p["correct"] else "✗ факт потерян"
        print(f"  ── {p['label']}  [факт в окне: {p['fact_present']}] → {mark}")
        print(f"     {p['reply'].strip()[:220]}\n")
    print("  → Инвариант: факт в окне → верно; факт выпал → НЕ верно.")
    print("    Проявляется то как отказ, то как уверенная ВЫДУМКА (конфабуляция) — варьируется.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["json", "sqlite"], default="json")
    args = ap.parse_args()

    if args.store == "json":
        memory = JsonMemory(os.path.join(HERE, "memory.json"))
    else:
        memory = SqliteMemory(os.path.join(HERE, "memory.db"))

    agent = Agent(
        system_prompt="Ты — лаконичный ассистент. Отвечай по-русски, по делу.",
        model=MODEL, memory=memory, name="Агент",
    )

    n = len(agent.history)
    print(f"[память: загружено {n} сообщений с диска]" if n else "[память пуста]")
    print("[команды: /cost /overflow /forget /clear /exit]")

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
            print("[память и бухгалтерия стёрты]")
            continue
        if text == "/cost":
            cmd_cost(agent)
            continue
        if text == "/overflow":
            cmd_overflow(agent)
            continue
        if text == "/forget":
            cmd_forget(agent)
            continue

        print(f"{agent.name}> ", end="", flush=True)
        agent.send(text, printer=lambda t: print(t, end="", flush=True))
        print()
        if agent.ledger:
            print(fmt_meter(agent.ledger[-1]))


if __name__ == "__main__":
    sys.exit(main())

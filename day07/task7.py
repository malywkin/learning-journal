"""День 7 — CLI: агент, который переживает перезапуск.

Запуск:
    .venv/bin/python task7.py                # память в JSON (memory.json)
    .venv/bin/python task7.py --store sqlite # память в SQLite (memory.db)

Проверка по заданию: поговори → закрой (Ctrl+C или /exit) → запусти снова →
агент помнит. Команды: /exit — выход, /clear — стереть память, /history — что
загружено/накоплено.
"""
import argparse
import os
import sys
from dotenv import load_dotenv

from agent import Agent
from memory import JsonMemory, SqliteMemory

load_dotenv()
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "openai/gpt-oss-20b:free"            # надёжная бесплатная (см. День 5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["json", "sqlite"], default="json",
                    help="куда сохранять историю (по умолчанию json)")
    args = ap.parse_args()

    # «Папка дела»: JSON-файл или база SQLite — агенту всё равно (общие ручки).
    if args.store == "json":
        memory = JsonMemory(os.path.join(HERE, "memory.json"))
    else:
        memory = SqliteMemory(os.path.join(HERE, "memory.db"))

    agent = Agent(
        system_prompt="Ты — лаконичный ассистент. Отвечай по-русски, по делу.",
        model=MODEL,
        memory=memory,
    )

    n = len(agent.history)
    if n:
        print(f"[память: загружено {n} сообщений из прошлых запусков — продолжаем]")
        last = agent.history[-1]
        print(f"[последняя реплика ({last['role']}): {last['content'][:80]}...]")
    else:
        print("[память пуста — начинаем новый разговор]")

    while True:
        try:
            text = input("\nты> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[выход; история уже на диске — ничего сохранять не надо]")
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/clear":
            agent.reset()
            print("[память стёрта — и в программе, и на диске]")
            continue
        if text == "/history":
            print(f"[в истории {len(agent.history)} сообщений; "
                  f"в модель уйдут последние {agent.max_turns} ходов]")
            continue

        print(f"{agent.name}> ", end="", flush=True)
        agent.send(text, printer=lambda t: print(t, end="", flush=True))
        print()


if __name__ == "__main__":
    sys.exit(main())

"""День 6 — CLI-чат поверх агента (главный запускаемый файл).

Интерфейс (см. задание: «простой чат, CLI или web») максимально тонкий: он НЕ знает,
как устроен вызов LLM — он только читает ввод, отдаёт его агенту и печатает ответ.
Вся логика запроса/ответа живёт в классе Agent (agent.py). В этом и смысл задания:
агент — отдельная сущность, интерфейс — лишь «лицо».

Запуск:  .venv/bin/python task6.py
Команды: /reset — забыть разговор · /history — показать память · /exit — выход
"""
import os
from dotenv import load_dotenv
from agent import Agent

# .env лежит рядом с этим файлом — берём ключ оттуда (не хардкодим).
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# РОЛЬ агента. Поменяй текст — поменяется характер/поведение, код трогать не нужно.
SYSTEM_PROMPT = (
    "Ты — вежливый помощник-ассистент. Отвечай кратко и по делу, на русском языке. "
    "Если чего-то не знаешь — честно скажи, что не знаешь, не выдумывай."
)
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")


def main():
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, name="Ассистент")
    print(f"🤖 {agent.name} на модели {MODEL}")
    print("Команды: /reset  /history  /exit\n")

    while True:
        try:
            user = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user:
            continue
        if user == "/exit":
            break
        if user == "/reset":
            agent.reset()
            print("[память очищена — начинаем с чистого листа]\n")
            continue
        if user == "/history":
            print(f"[в памяти {len(agent.history)} сообщений]")
            for m in agent.history:
                print(f"  {m['role']:>9}: {m['content'][:80]}")
            print()
            continue

        # Живой вывод: печатаем токены по мере прихода (стриминг из дня 5).
        print(f"{agent.name}: ", end="", flush=True)
        agent.send(user, printer=lambda t: print(t, end="", flush=True))
        print("\n")


if __name__ == "__main__":
    main()

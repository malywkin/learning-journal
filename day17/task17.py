"""
День 17 — CLI к агенту с MCP-инструментами.

Сам поднимает MCP-сервер (mcp_server.py) и общается с агентом. На каждый вызов,
который ПИШЕТ в CRM, спрашивает подтверждение (человек-в-цикле).

  python task17.py            # интерактивный чат
  python task17.py --demo     # прогон сценариев без ввода (для проверки/видео)
"""

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx

from agent import CrmAgent, SERVER_URL

HERE = Path(__file__).parent


def spawn_server() -> subprocess.Popen:
    """Поднимаем MCP-сервер подпроцессом и ждём, пока он начнёт отвечать."""
    proc = subprocess.Popen([sys.executable, str(HERE / "mcp_server.py")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.25)
        try:
            # сервер на этом порту отвечает (любой код != отказ соединения = живой)
            httpx.post(SERVER_URL, timeout=1)
            return proc
        except httpx.ConnectError:
            continue
        except Exception:
            return proc
    return proc


def print_trace(trace: list[dict]) -> None:
    for s in trace:
        if s["type"] == "tools_offered":
            print(f"   · клиент взял меню инструментов: {', '.join(s['tools'])}")
        elif s["type"] == "tool_call":
            mark = "✍️ ЗАПИСЬ" if s["writes"] else "👁 чтение"
            ok = "" if s["confirmed"] else "  [ОТКЛОНЕНО человеком]"
            print(f"   · модель вызвала {s['name']}  {mark}{ok}")
            print(f"        аргументы: {s['args']}")
            if s.get("result_structured") is not None:
                print(f"        результат: {s['result_structured']}")


def ask_confirm(name: str, args: dict) -> bool:
    print(f"\n   ⚠️  Агент хочет ВЫПОЛНИТЬ запись через «{name}»")
    print(f"       аргументы: {args}")
    return input("       выполнить? [y/N] ").strip().lower() in ("y", "yes", "д", "да")


async def interactive(agent: CrmAgent) -> None:
    print("Чат с CRM-агентом. Примеры: «покажи активных клиентов», "
          "«заведи клиента Иванова, lead». Выход — пустая строка.\n")
    history: list[dict] = []
    while True:
        try:
            q = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        res = await agent.ask(q, history)
        print_trace(res["trace"])
        print(f"\nАгент: {res['answer']}\n")
        history += [{"role": "user", "content": q},
                    {"role": "assistant", "content": res["answer"]}]


async def demo(agent: CrmAgent) -> None:
    # В демо отклоняем запись, если в имени есть «Отказ» — показываем обе ветки HITL.
    agent.on_confirm = lambda name, args: "Отказ" not in str(args.get("name", ""))
    scenarios = [
        "Покажи всех активных клиентов.",
        "Заведи нового клиента: Сидоров Иван, стадия active, заметка «новый договор поставки».",
        "Заведи клиента: Тестовый Отказ, стадия lead.",   # эту запись человек отклонит
        "Найди клиента Сидорова и подтверди, что он в базе.",
    ]
    for q in scenarios:
        print(f"\n{'='*70}\nВы: {q}")
        res = await agent.ask(q)
        print_trace(res["trace"])
        print(f"\nАгент: {res['answer']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="прогон сценариев без ввода")
    args = ap.parse_args()

    server = spawn_server()
    try:
        agent = CrmAgent(on_confirm=ask_confirm)
        if args.demo:
            await demo(agent)
        else:
            await interactive(agent)
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    asyncio.run(main())

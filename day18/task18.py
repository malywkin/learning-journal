"""
День 18 — CLI к серверу с планировщиком (без LLM-агента, чистый MCP-клиент).

Показывает то же, что витрина, но текстом: поставить задачу, выполнить сейчас, посмотреть
расписание и состояние, забрать сводку. Сервер mcp_server.py должен быть запущен отдельно
(или подними его: python mcp_server.py).

  python task18.py --demo            # сценарий: запланировать → тикнуть → показать сводку
  python task18.py                   # интерактив: collect/schedule/digest/jobs/status/remind/quit
"""

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://127.0.0.1:8018/mcp"


async def call(session, tool, **args):
    res = await session.call_tool(tool, args)
    if res.structuredContent:
        return res.structuredContent
    if res.content and getattr(res.content[0], "text", None):
        try:
            return json.loads(res.content[0].text)
        except json.JSONDecodeError:
            return {"text": res.content[0].text}
    return {}


def show_jobs(d):
    jobs = d.get("jobs", [])
    if not jobs:
        print("  (расписание пусто)")
    for j in jobs:
        nxt = j.get("next_run") or "разовая/завершена"
        print(f"  • {j['id']:<26} {j['trigger']:<26} след: {nxt}")


def show_status(s):
    print(f"  постов собрано: {s.get('posts',0)} | сводок: {s.get('digests',0)}")
    for r in s.get("recent_runs", [])[:6]:
        print(f"    - {r['detail']}")
    d = s.get("latest_digest")
    if d and d.get("summary"):
        print("  последняя сводка:\n   ", d["summary"].replace("\n", "\n    "))


async def demo(sub="LocalLLaMA"):
    async with streamablehttp_client(SERVER_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print(f"== ставлю периодический сбор r/{sub} (каждую 1 мин) ==")
            print(" ", (await call(s, "schedule_collection", subreddit=sub, every_minutes=1))["message"])
            print("== выполняю сбор СЕЙЧАС (не ждём интервал) ==")
            print(" ", await call(s, "run_now", subreddit=sub, kind="collect"))
            print("== делаю сводку СЕЙЧАС ==")
            res = await call(s, "run_now", subreddit=sub, kind="digest")
            print("  сводка:", (res.get("summary") or res.get("error", ""))[:400])
            print("== расписание ==");  show_jobs(await call(s, "list_jobs"))
            print("== состояние ==");   show_status(await call(s, "get_status", subreddit=sub))
            print("\nПодсказка: перезапусти mcp_server.py — задача сбора поднимется с диска сама.")


async def repl():
    async with streamablehttp_client(SERVER_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("Команды: collect <sub> | schedule <sub> <min> | digest <sub> | "
                  "jobs | status <sub> | remind <min> <текст> | quit")
            loop = asyncio.get_event_loop()
            while True:
                line = (await loop.run_in_executor(None, input, "> ")).strip()
                if not line:
                    continue
                parts = line.split()
                cmd = parts[0]
                try:
                    if cmd == "quit":
                        break
                    elif cmd == "collect":
                        print(await call(s, "run_now", subreddit=parts[1], kind="collect"))
                    elif cmd == "schedule":
                        print((await call(s, "schedule_collection", subreddit=parts[1], every_minutes=int(parts[2])))["message"])
                    elif cmd == "digest":
                        res = await call(s, "run_now", subreddit=parts[1], kind="digest")
                        print((res.get("summary") or res.get("error", ""))[:500])
                    elif cmd == "jobs":
                        show_jobs(await call(s, "list_jobs"))
                    elif cmd == "status":
                        show_status(await call(s, "get_status", subreddit=parts[1]))
                    elif cmd == "remind":
                        print((await call(s, "add_reminder", text=" ".join(parts[2:]), in_minutes=float(parts[1])))["message"])
                    else:
                        print("неизвестная команда")
                except (IndexError, ValueError):
                    print("проверь аргументы команды")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(demo())
    else:
        asyncio.run(repl())

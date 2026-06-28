"""
День 20 — CLI-обёртка: прогнать длинный флоу через три MCP-сервера из терминала, без витрины.
Сами серверы должны быть уже подняты (reddit_server.py / storage_server.py / utils_server.py),
либо запускай всё разом через run.py.

  python task20.py LocalLLaMA            # дайджест r/LocalLLaMA → перевод → время → заметка
  python task20.py MachineLearning rag   # с фильтром по теме
"""

import asyncio
import json
import sys

import host

if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else "LocalLLaMA"
    q = sys.argv[2] if len(sys.argv) > 2 else ""
    out = asyncio.run(host.run_flow(sub, q))

    print(f"\nсерверы в деле: {', '.join(out['servers_used'])}")
    print(f"порядок вызовов: {' → '.join(out['sequence'])}")
    print(f"инструменты с разных серверов: {'да' if out['cross_server'] else 'нет'}")
    print(f"порядок корректен: {'да' if out['order_ok'] else 'НЕТ — ' + str(out['violations'])}")
    if out.get("file_path"):
        print(f"заметка: {out['file_path']}")

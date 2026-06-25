"""
День 16 — веб-витрина к MCP-клиенту («стеклянный капот»).

Тонкий FastAPI-сервер. Делает ровно две вещи:
  • отдаёт страницу index.html;
  • на запрос /api/tools подключается к готовому MCP-серверу (DeepWiki / MS Learn),
    делает рукопожатие и возвращает его список инструментов + замеры шагов.

Вся «магия» MCP — та же, что в task16.py; здесь она просто завёрнута в веб,
чтобы было видно глазами.
"""

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Готовые публичные MCP-серверы без авторизации.
SERVERS = {
    "deepwiki": ("DeepWiki", "https://mcp.deepwiki.com/mcp"),
    "mslearn": ("Microsoft Learn", "https://learn.microsoft.com/api/mcp"),
}

app = FastAPI()
HERE = Path(__file__).parent


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/api/tools")
async def api_tools(server: str = "deepwiki"):
    if server not in SERVERS:
        return JSONResponse({"error": "неизвестный сервер"}, status_code=400)

    name, url = SERVERS[server]
    steps: list[dict] = []
    t0 = time.perf_counter()

    def mark(label: str) -> None:
        steps.append({"label": label, "ms": round((time.perf_counter() - t0) * 1000)})

    try:
        # 1) открываем соединение по сети (Streamable HTTP)
        async with streamablehttp_client(url) as (read, write, _):
            mark("Открыл соединение по сети (Streamable HTTP)")
            async with ClientSession(read, write) as session:
                # 2) рукопожатие — без него сервер не отвечает
                init = await session.initialize()
                mark("Рукопожатие (initialize)")
                # 3) сам запрос «дай список инструментов»
                result = await session.list_tools()
                mark("Запросил список инструментов (tools/list)")

                tools = [
                    {
                        "name": t.name,
                        "description": (t.description or "").strip(),
                        "inputSchema": t.inputSchema or {},
                    }
                    for t in result.tools
                ]
                return {
                    "server": {
                        "label": name,
                        "name": init.serverInfo.name,
                        "version": init.serverInfo.version,
                        "url": url,
                    },
                    "steps": steps,
                    # как выглядит сам запрос на проводе (формат JSON-RPC)
                    "request": {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    "tools": tools,
                }
    except Exception as e:
        return JSONResponse(
            {"error": f"{type(e).__name__}: {e}", "server": name}, status_code=502
        )

"""
День 18 — веб-витрина «стеклянный капот» к ассистенту, который работает по расписанию.

Две линии, нарочно разведённые, чтобы было видно суть дня:
  • ЖИВАЯ ЛЕНТА (чтение) — витрина читает SQLite напрямую и каждые 2 сек показывает, что
    планировщик натикал: сколько постов собрано, какие сводки, журнал срабатываний.
    Сервер ничего не «пушит» — мы сами приходим за состоянием (pull).
  • ДЕЙСТВИЯ (запись) — кнопки зовут НАСТОЯЩИЕ MCP-инструменты сервера (schedule_collection,
    run_now, add_reminder, cancel_job) через Streamable HTTP. То есть расписанием рулим
    именно как MCP-инструментами, а не из веба напрямую.

Сервер mcp_server.py поднимается отдельно (его стартует run.py). Планировщик живёт в нём.
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import collector

app = FastAPI()
HERE = Path(__file__).parent
MCP_URL = "http://127.0.0.1:8018/mcp"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


async def _mcp_call(tool: str, args: dict) -> dict:
    """Позвать MCP-инструмент сервера и вернуть его результат как dict."""
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(tool, args)
            if res.structuredContent:
                return res.structuredContent
            if res.content and getattr(res.content[0], "text", None):
                try:
                    return json.loads(res.content[0].text)
                except json.JSONDecodeError:
                    return {"text": res.content[0].text}
            return {}


@app.get("/api/status")
def api_status(subreddit: str = "LocalLLaMA"):
    """Живое состояние из SQLite напрямую (быстро, без MCP-рукопожатия на каждый опрос)."""
    return collector.status(subreddit)


class Action(BaseModel):
    tool: str
    args: dict = {}


@app.post("/api/action")
async def api_action(req: Action):
    """Единая точка для ДЕЙСТВИЙ — зовёт MCP-инструмент сервера (расписание/сбор/отмена)."""
    try:
        return await _mcp_call(req.tool, req.args)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)

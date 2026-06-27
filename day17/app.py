"""
День 17 — веб-витрина «стеклянный капот» к агенту с MCP-инструментом.

Тонкий FastAPI. Разбивает один заход агента на ТРИ видимых шага, чтобы было видно
самое важное — человека-в-цикле перед записью:

  /api/plan     — клиент берёт у сервера меню инструментов (tools/list) и спрашивает
                  модель, что делать. Модель РЕШАЕТ: позвать инструмент (какой, с какими
                  аргументами) или ответить сразу. Вызов ещё НЕ выполнен.
  /api/execute  — человек подтвердил → выполняем tools/call на сервере, результат
                  возвращаем модели, она формулирует финальный ответ. Либо человек
                  отклонил запись → вызова нет.

Упрощение (честно): показываем ОДИН ход агента (один инструмент). Настоящий агент
крутит цикл из многих вызовов — это «лестница зрелости», см. takeaways.

Сервер mcp_server.py поднимается отдельно (его стартует run.py / task17).
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent import (SERVER_URL, MODEL, SYSTEM, _client, _llm_with_retry,
                   mcp_tools_to_openai)

app = FastAPI()
HERE = Path(__file__).parent
llm = _client()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


def _tools_view(tool_list) -> list[dict]:
    """Меню инструментов для показа в витрине: имя, описание, схема, read/write."""
    view = []
    for t in tool_list:
        ann = t.annotations
        view.append({
            "name": t.name,
            "title": getattr(ann, "title", None) if ann else None,
            "description": t.description or "",
            "readOnly": bool(getattr(ann, "readOnlyHint", False)) if ann else False,
            "inputSchema": t.inputSchema or {},
        })
    return view


class PlanReq(BaseModel):
    message: str


@app.post("/api/plan")
async def api_plan(req: PlanReq):
    """Шаг 1: меню инструментов + решение модели (без выполнения вызова)."""
    try:
        async with streamablehttp_client(SERVER_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tool_list = (await session.list_tools()).tools
                tools_view = _tools_view(tool_list)
                read_only = {t["name"]: t["readOnly"] for t in tools_view}

                resp = _llm_with_retry(
                    llm, model=MODEL,
                    messages=[{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": req.message}],
                    tools=mcp_tools_to_openai(tool_list),
                    tool_choice="auto", max_tokens=1200,
                    extra_body={"reasoning": {"effort": "low"}},
                )
                msg = resp.choices[0].message
                out = {
                    "server": {"name": init.serverInfo.name, "version": init.serverInfo.version, "url": SERVER_URL},
                    "tools": tools_view,
                }
                if not msg.tool_calls:
                    out["decision"] = {"kind": "final", "text": msg.content or ""}
                    return out

                tc = msg.tool_calls[0]
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                name = tc.function.name
                out["decision"] = {
                    "kind": "tool",
                    "name": name,
                    "args": args,
                    "writes": not read_only.get(name, False),
                    # как вызов выглядит на проводе (JSON-RPC поверх Streamable HTTP)
                    "jsonrpc": {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": name, "arguments": args}},
                }
                return out
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)


class ExecReq(BaseModel):
    message: str
    name: str
    args: dict
    approved: bool


@app.post("/api/execute")
async def api_execute(req: ExecReq):
    """Шаг 2: человек решил. approved=False → запись отклонена, вызова нет."""
    if not req.approved:
        return {"executed": False,
                "answer": "Запись отклонена человеком — вызов инструмента не выполнен."}
    try:
        async with streamablehttp_client(SERVER_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                call = await session.call_tool(req.name, req.args)
                result_text = call.content[0].text if call.content else ""

                # Возвращаем результат модели, чтобы она ответила человеку по-русски.
                fake_id = "call_1"
                messages = [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": req.message},
                    {"role": "assistant", "content": "",
                     "tool_calls": [{"id": fake_id, "type": "function",
                                     "function": {"name": req.name, "arguments": json.dumps(req.args, ensure_ascii=False)}}]},
                    {"role": "tool", "tool_call_id": fake_id, "content": result_text},
                ]
                resp = _llm_with_retry(llm, model=MODEL, messages=messages,
                                       max_tokens=800, extra_body={"reasoning": {"effort": "low"}})
                answer = resp.choices[0].message.content or ""
                return {"executed": True, "result_structured": call.structuredContent,
                        "result_text": result_text, "answer": answer}
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)

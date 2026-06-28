"""
День 19 — веб-витрина «стеклянный капот» к композиции MCP-инструментов.

Одна страница, один переключатель: один и тот же набор из трёх MCP-инструментов
(search → summarize → save_to_file) прогоняется ДВУМЯ оркестраторами:
  • «Жёсткий пайплайн» — порядок ведёт код (pipeline.py): 1 вызов LLM, 0 решений-выборов;
  • «Агент сам»        — порядок выбирает модель (agent.py, tool_choice=auto): несколько
    вызовов LLM, модель сама решает, что звать.

Витрина показывает цепочку шагами (загораются по очереди), видимую передачу данных между
шагами (выход одного = вход следующего) и честный счётчик «цены гибкости».

Сервер mcp_server.py поднимается отдельно (его стартует run.py).  Запуск:  python run.py
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import agent
import pipeline

app = FastAPI()
HERE = Path(__file__).parent
OUT_DIR = HERE / "output"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


class RunReq(BaseModel):
    mode: str = "pipeline"          # pipeline | agent
    subreddit: str = "LocalLLaMA"
    query: str = ""


@app.post("/api/run")
async def api_run(req: RunReq):
    """Прогнать цепочку выбранным оркестратором и вернуть трассу для анимации."""
    sub = req.subreddit.strip() or "LocalLLaMA"
    try:
        if req.mode == "agent":
            return await agent.run_agent(sub, req.query.strip())
        return await pipeline.run_pipeline(sub, req.query.strip())
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=502)


@app.get("/api/file", response_class=PlainTextResponse)
def api_file(name: str):
    """Показать содержимое сохранённого файла (только из папки output/, без выхода наружу)."""
    safe = Path(name).name
    path = OUT_DIR / safe
    if not path.exists():
        return PlainTextResponse("файл не найден", status_code=404)
    return path.read_text(encoding="utf-8")

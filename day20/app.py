"""
День 20 — веб-витрина «стеклянный капот» к оркестрации НЕСКОЛЬКИХ MCP-серверов.

Одна страница показывает три сервера (reddit / storage / utils), единый список их
инструментов, который видит модель, и живую трассу: на каком шаге модель ВЫБРАЛА инструмент,
на КАКОЙ сервер хост его направил и в каком ПОРЯДКЕ шла цепочка. Внизу — проверка из задания:
задействованы ли инструменты с разных серверов и не нарушен ли порядок.

Три MCP-сервера поднимаются отдельными процессами (их стартует run.py).  Запуск:  python run.py
"""

import traceback
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import host

app = FastAPI()
HERE = Path(__file__).parent
NOTES_DIR = HERE / "notes"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


class RunReq(BaseModel):
    subreddit: str = "LocalLLaMA"
    query: str = ""


@app.post("/api/run")
async def api_run(req: RunReq):
    """Прогнать длинный флоу через три сервера и вернуть трассу для анимации."""
    sub = req.subreddit.strip() or "LocalLLaMA"
    try:
        return await host.run_flow(sub, req.query.strip())
    except Exception as e:
        traceback.print_exc()  # в лог веба — чтобы причина (часто 429 free-tier) была видна
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=502)


@app.get("/api/note", response_class=PlainTextResponse)
def api_note(name: str):
    """Показать сохранённую заметку (только из папки notes/, без выхода наружу)."""
    path = NOTES_DIR / Path(name).name
    if not path.exists():
        return PlainTextResponse("заметка не найдена", status_code=404)
    return path.read_text(encoding="utf-8")

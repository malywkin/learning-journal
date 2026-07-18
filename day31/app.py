"""
День 31 — веб-лицо ассистента (тонкий FastAPI). Продукт — окно чата в браузере,
НЕ терминал: F не работает в консоли (память prefers-gui-app-not-terminal).

Тонкий слой: вся логика в router.py, здесь только HTTP + отдача страницы. Паттерн
Дней 30/24 (FastAPI перед мотором). При старте поднимаем ОДНУ живую MCP-сессию к
git-серверу (lifespan) и держим её на всё время работы приложения.
"""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import router

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Одна MCP-сессia на всё приложение (не поднимаем под-процесс на каждый запрос).
    async with AsyncExitStack() as stack:
        app.state.hub = await router.ToolHub.create(stack)
        app.state.lock = asyncio.Lock()      # MCP-сессия одна — сериализуем запросы
        yield
    # выход из стека закроет сессию и погасит git-под-процесс


app = FastAPI(title="Ассистент разработчика — День 31", lifespan=lifespan)


class Ask(BaseModel):
    question: str
    history: list[dict] = []


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.post("/chat")
async def chat(ask: Ask):
    q = (ask.question or "").strip()
    if not q:
        return JSONResponse({"answer": "Пустой вопрос.", "trace": [], "provider": "none"})
    # История — только текстовые пары user/assistant (без внутренностей тулзов).
    hist = [m for m in ask.history if m.get("role") in ("user", "assistant") and m.get("content")]
    async with app.state.lock:
        res = await router.answer(q, app.state.hub, history=hist[-8:])
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8031, log_level="warning")

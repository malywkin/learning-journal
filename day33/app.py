"""
День 33 — веб-лицо ассистента поддержки (тонкий FastAPI). Продукт — окно чата в браузере,
НЕ терминал (память prefers-gui-app-not-terminal). Каркас Дня 31 один в один: вся логика в
router.py, здесь только HTTP + отдача страницы + одна живая MCP-сессия на всё приложение.

Добавлено против Дня 31: переключатель «кто пишет» (/personas) — в реальном виджете клиент
уже вошёл, поэтому его тикет известен; мы передаём ticket_id в мотор, а тот сам достаёт
карточку (get_ticket) — видно в следе инструментов.
"""
import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
import router

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Одна MCP-сессия к серверу тикетов на всё приложение (не поднимаем под-процесс на запрос).
    async with AsyncExitStack() as stack:
        app.state.hub = await router.ToolHub.create(stack)
        app.state.lock = asyncio.Lock()      # MCP-сессия одна — сериализуем запросы
        yield
    # выход из стека закроет сессию и погасит под-процесс сервера тикетов


app = FastAPI(title=f"Поддержка «{config.PRODUCT_NAME}» — День 33", lifespan=lifespan)


class Ask(BaseModel):
    question: str
    history: list[dict] = []
    ticket_id: str | None = None


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/personas")
async def personas():
    """Демо-клиенты для переключателя «кто пишет» (кто, тариф, его открытый тикет)."""
    db = json.loads(Path(config.TICKETS_JSON).read_text(encoding="utf-8"))
    users = {u["id"]: u for u in db.get("users", [])}
    out = []
    for t in db.get("tickets", []):
        u = users.get(t.get("user_id"), {})
        out.append({"ticket_id": t["id"], "name": u.get("name", "—"),
                    "plan": u.get("plan", "—"), "subject": t["subject"]})
    return JSONResponse(out)


@app.post("/chat")
async def chat(ask: Ask):
    q = (ask.question or "").strip()
    if not q:
        return JSONResponse({"answer": "Пустой вопрос.", "trace": [], "provider": "none"})
    # История — только текстовые пары user/assistant (без внутренностей тулзов).
    hist = [m for m in ask.history if m.get("role") in ("user", "assistant") and m.get("content")]
    async with app.state.lock:
        res = await router.answer(q, app.state.hub, history=hist[-8:], ticket_id=ask.ticket_id)
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8033, log_level="warning")

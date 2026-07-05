"""
День 25 — веб-обвязка мини-чата (тёмная тема, как в днях по MCP).

Тонкий слой поверх chat.py: держит сессии в памяти, на каждый ход возвращает
ответ + источники + карточку задачи. Вся механика — в chat.py / grounded.py.

Запуск:  ../day21/.venv/bin/uvicorn app:app --port 8250
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import chat
import grounded as g

app = FastAPI(title="День 25 — мини-чат RAG + память задачи")
BASE = Path(__file__).parent

# сессии в памяти: session_id → ChatSession (история + карточка живут между ходами)
SESSIONS: dict[str, chat.ChatSession] = {}


def _session(sid: str) -> chat.ChatSession:
    if sid not in SESSIONS:
        SESSIONS[sid] = chat.ChatSession()
    return SESSIONS[sid]


class Msg(BaseModel):
    message: str
    session_id: str = "web"


class Sid(BaseModel):
    session_id: str = "web"


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.post("/chat")
def chat_turn(m: Msg):
    """Один ход диалога: контекстуализация → ответ по источникам → обновление карточки."""
    return _session(m.session_id).turn(m.message)


@app.post("/reset")
def reset(s: Sid):
    SESSIONS[s.session_id] = chat.ChatSession()
    return {"ok": True, "task_state": SESSIONS[s.session_id].state}


@app.get("/health")
def health():
    return {"ok": True, "provider": g.PROVIDER, "model": g.MODEL}

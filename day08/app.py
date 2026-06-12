"""День 8 — Агент со счётчиком токенов: тонкий бэкенд (FastAPI).

«Провод» между страницей (index.html) и агентом (agent.py + tokens.py + demos.py).
Три демонстрации дня:
  • СЧЁТЧИК   — после каждого хода отдаём токены из серверного usage (вход/выход/всего)
               + нашу локальную прикидку + «как если бы» цену;
  • РОСТ      — бухгалтерия по ходам (вход растёт, цена нарастает);
  • ПОЛОМКА   — /api/overflow (реальная ошибка 400) и /api/forget (потеря контекста).

Запуск:
    .venv/bin/python app.py   →   http://127.0.0.1:8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from agent import Agent
from demos import run_forget, run_overflow
from memory import JsonMemory
from tokens import ENC_NAME, PRICE_IN, PRICE_OUT, window_for

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = "Ты — вежливый помощник-ассистент. Отвечай кратко и по делу, на русском языке."
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")

# Память на диске (наследие Дня 7) — чтобы рост истории был «настоящим».
memory = JsonMemory(os.path.join(HERE, "memory.json"))
agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, memory=memory, name="Ассистент")

app = FastAPI(title="Агент со счётчиком токенов — День 8")


def state():
    return {
        "model": MODEL,
        "encoder": ENC_NAME,
        "window": window_for(MODEL),
        "price_in": PRICE_IN,
        "price_out": PRICE_OUT,
        "history": agent.history,
        "ledger": agent.ledger,     # бухгалтерия по ходам (токены + цена)
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/api/state")
def get_state():
    return JSONResponse(state())


@app.post("/api/chat")
async def chat(req: Request):
    data = await req.json()
    user_msg = (data.get("message") or "").strip()
    reply = agent.send(user_msg)
    return JSONResponse({"reply": reply, **state()})


@app.post("/api/clear")
def clear():
    agent.reset()
    return JSONResponse(state())


@app.post("/api/overflow")
def overflow():
    """Сценарий А: довести запрос до переполнения окна → реальная ошибка 400."""
    return JSONResponse(run_overflow(agent))


@app.post("/api/forget")
def forget():
    """Сценарий Б: потеря контекста (помнит / отказ / конфабуляция)."""
    return JSONResponse(run_forget(agent))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

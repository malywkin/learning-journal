"""День 6 — Агент со «стеклянным капотом»: тонкий бэкенд (FastAPI).

Этот файл — ТОЛЬКО «провод» между красивой страницей (index.html) и агентом
(agent.py). Вся логика запроса/ответа живёт в классе Agent — здесь лишь три ручки:
  GET  /            — отдать страницу;
  POST /api/chat    — {message, memory, role} → агент → {reply, sent};
  POST /api/reset   — очистить память агента.

Запуск:  .venv/bin/python app.py   →  открой http://127.0.0.1:8000
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from agent import Agent

HERE = os.path.dirname(__file__)
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = (
    "Ты — вежливый помощник-ассистент. Отвечай кратко и по делу, на русском языке. "
    "Если чего-то не знаешь — честно скажи, что не знаешь, не выдумывай."
)
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")

# Один агент на приложение (локальное демо на одного пользователя).
agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, name="Ассистент")

app = FastAPI(title="Стеклянный агент — День 6")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.post("/api/chat")
async def chat(req: Request):
    data = await req.json()
    user_msg = (data.get("message") or "").strip()
    memory_on = bool(data.get("memory", True))
    agent.system_prompt = data.get("role") or SYSTEM_PROMPT  # применяем текущую роль

    reply = agent.send(user_msg, remember=memory_on)         # ← вся логика внутри агента
    # agent.last_sent — это ТОЧНО то, что ушло в модель (для панели «под капотом»).
    return JSONResponse({"reply": reply, "sent": agent.last_sent})


@app.post("/api/reset")
def reset():
    agent.reset()
    return {"ok": True}


@app.get("/api/default_role")
def default_role():
    return {"role": SYSTEM_PROMPT}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

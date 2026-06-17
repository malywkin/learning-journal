"""День 11 — веб-«капот»: тонкий бэкенд (FastAPI) над моделью памяти из 3 слоёв.

«Провод» между страницей (index.html) и агентом (agent.py + memory_layers.py).
Показывает ровно задание: три раздельных слоя памяти, видно ЧТО роутер положил в
каждый после реплики, и как долговременный слой меняет ответ (тумблер «профиль»).

Запуск:
    .venv/bin/python app.py   →   http://127.0.0.1:8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from agent import Agent
from demos import run_influence

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = ("Ты — ассистент-помощник разработчика. Отвечай по-русски, по делу. "
                 "Учитывай профиль пользователя и данные задачи, если они даны.")
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")
KEEP_LAST = 6

# веб-демо стартует «с чистого листа» (без файлов) — состояние в памяти процесса
agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, short_keep=KEEP_LAST, paths=None)

app = FastAPI(title="Модель памяти ассистента — День 11")


def state():
    v = agent.memory.view()
    last_route = v["routes"][-1] if v["routes"] else None
    last = agent.ledger[-1] if agent.ledger else None
    return {
        "model": MODEL,
        "keep_last": KEEP_LAST,
        "short": v["short"],            # messages, window, dropped, keep_last
        "working": v["working"],        # text, fields
        "longterm": v["longterm"],      # text, fields
        "last_route": last_route,       # что роутер решил на прошлой реплике
        "last_sent": agent.last_sent,   # что РЕАЛЬНО ушло в модель
        "input_tokens": (last or {}).get("usage", {}).get("prompt_tokens") if last else None,
        "router_tokens": sum(r.get("router_tokens", 0) for r in agent.ledger),
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
    use_lt = data.get("use_longterm", True)        # тумблер «профиль» из UI
    reply = agent.send(user_msg, use_longterm=use_lt)
    return JSONResponse({"reply": reply, "used_longterm": use_lt, **state()})


@app.post("/api/new_task")
def new_task():
    """Новая задача: рабочая и диалог — очистить, профиль оставить."""
    agent.memory.new_task()
    return JSONResponse(state())


@app.post("/api/clear")
def clear():
    agent.reset()
    return JSONResponse(state())


@app.post("/api/influence")
def influence():
    """Один вопрос — два ответа (с профилем и без), на чистом диалоге. Реальные вызовы."""
    res = run_influence(agent)
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

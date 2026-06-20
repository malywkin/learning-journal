"""День 12 — веб-«капот»: тонкий бэкенд (FastAPI) над персонализированным агентом.

«Провод» между страницей (index.html) и агентом (agent.py + memory_layers.py).
Показывает ровно задание: профиль из двух частей (заданное тобой + замеченное
автоматически), тумблер «профиль ON/OFF» (видно влияние на ответ), ввод предпочтения
и сравнение двух профилей на одном вопросе.

Запуск:
    .venv/bin/python app.py   →   http://127.0.0.1:8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from agent import Agent
from demos import run_two_profiles

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = ("Ты — ассистент-помощник. Отвечай по-русски. Строго соблюдай профиль "
                 "пользователя (стиль, формат, ограничения), если он задан.")
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")
KEEP_LAST = 6

# веб-демо стартует «с чистого листа» (без файлов) — состояние в памяти процесса
agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, short_keep=KEEP_LAST, paths=None)

app = FastAPI(title="Персонализация ассистента — День 12")


def state():
    v = agent.memory.view()
    last_route = v["routes"][-1] if v["routes"] else None
    last = agent.ledger[-1] if agent.ledger else None
    return {
        "model": MODEL,
        "keep_last": KEEP_LAST,
        "short": v["short"],
        "working": v["working"],
        "profile": v["profile"],            # stated{text,fields}, noticed{text,fields}
        "profile_block": v["profile_block"],  # что реально подмешивается в запрос
        "last_route": last_route,
        "last_sent": agent.last_sent,
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
    use_profile = data.get("use_profile", True)        # тумблер «профиль» из UI
    reply = agent.send(user_msg, use_profile=use_profile)
    return JSONResponse({"reply": reply, "used_profile": use_profile, **state()})


@app.post("/api/preference")
async def preference(req: Request):
    """Задать предпочтение явно (как /pref в CLI): фраза → карточка stated."""
    data = await req.json()
    pref = (data.get("preference") or "").strip()
    res = agent.memory.state_preference(pref) if pref else {"added": []}
    return JSONResponse({"pref_result": res, **state()})


@app.post("/api/two_profiles")
def two_profiles():
    """Один вопрос — два профиля (юрист/разработчик), два ответа. Реальные вызовы."""
    res = run_two_profiles(agent)
    return JSONResponse({**res, **state()})


@app.post("/api/new_task")
def new_task():
    agent.memory.new_task()
    return JSONResponse(state())


@app.post("/api/clear")
def clear():
    agent.reset()
    return JSONResponse(state())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

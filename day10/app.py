"""День 10 — веб-«капот»: тонкий бэкенд (FastAPI) над тремя стратегиями.

«Провод» между страницей (index.html) и агентом (agent.py + strategies.py + demos.py).
Показывает ровно задание: переключатель Окно / Facts / Ветки + видно, ЧТО реально
уходит в модель на каждом режиме, и сравнение окно vs facts.

Запуск:
    .venv/bin/python app.py   →   http://127.0.0.1:8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from agent import Agent
from demos import run_compare
from strategies import Branching, SlidingWindow, StickyFacts
from tokens import estimate_messages, window_for

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = "Ты — вежливый ассистент, помогаешь собрать ТЗ. Отвечай кратко, по-русски."
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")
KEEP_LAST = 6   # ОКНО: последние 6 сообщений шлём дословно

agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, name="Ассистент")

# Три персистентные стратегии — карточка/ствол не теряются при переключении режима.
STRATEGIES = {
    "window": SlidingWindow(keep_last=KEEP_LAST),
    "facts": StickyFacts(agent.make_extractor(), keep_last=KEEP_LAST),
    "branch": Branching(),
}
MODE = "window"
agent.set_context(STRATEGIES[MODE])

app = FastAPI(title="Управление контекстом — три стратегии — День 10")


def envelope():
    """Что РЕАЛЬНО ушло в модель на последнем ходу, разобранное на отсеки (капот)."""
    sent = agent.last_sent or []
    systems = [m for m in sent if m["role"] == "system"]
    body = [m for m in sent if m["role"] != "system"]
    card = next((m["content"] for m in systems if m["content"].startswith("Карточка")), "")
    last = agent.ledger[-1] if agent.ledger else None
    return {
        "role_prompt": SYSTEM_PROMPT,
        "card": card,
        "window": body,                      # окно/ветка — дословные реплики
        "sent_count": len(sent),
        "input_tokens_real": (last or {}).get("usage", {}).get("prompt_tokens") if last else None,
        "input_estimate": estimate_messages(sent) if sent else None,
    }


def state():
    fview = STRATEGIES["facts"].view()
    bview = STRATEGIES["branch"].view()
    return {
        "mode": MODE,
        "model": MODEL,
        "window_size": window_for(MODEL),
        "keep_last": KEEP_LAST,
        "history": agent._current_history(),     # активная история (для веток — ствол+дельта)
        "full_history": agent.history,           # плоская история окна/facts
        "ledger": agent.ledger,
        "facts": fview.get("facts", ""),
        "facts_updates": fview.get("updates", 0),
        "branches": bview,
        "envelope": envelope(),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/api/state")
def get_state():
    return JSONResponse(state())


@app.post("/api/mode")
async def set_mode(req: Request):
    global MODE
    data = await req.json()
    m = data.get("mode")
    if m in STRATEGIES:
        MODE = m
        agent.set_context(STRATEGIES[m])
        if m == "facts":                       # догнать карточку по уже сказанному
            STRATEGIES["facts"].sync(agent.history)
    return JSONResponse(state())


@app.post("/api/chat")
async def chat(req: Request):
    data = await req.json()
    user_msg = (data.get("message") or "").strip()
    agent.set_context(STRATEGIES[MODE])
    reply = agent.send(user_msg)
    return JSONResponse({"reply": reply, **state()})


@app.post("/api/branch")
async def branch_op(req: Request):
    """Операции веток: checkpoint / fork / switch."""
    data = await req.json()
    op, name = data.get("op"), (data.get("name") or "").strip()
    br = STRATEGIES["branch"]
    if op == "checkpoint":
        br.checkpoint(name or "checkpoint")
    elif op == "fork" and name:
        br.fork(name)
    elif op == "switch" and name:
        br.switch(name)
    return JSONResponse(state())


@app.post("/api/clear")
def clear():
    global STRATEGIES
    agent.reset()
    STRATEGIES = {
        "window": SlidingWindow(keep_last=KEEP_LAST),
        "facts": StickyFacts(agent.make_extractor(), keep_last=KEEP_LAST),
        "branch": Branching(),
    }
    agent.set_context(STRATEGIES[MODE])
    return JSONResponse(state())


@app.post("/api/compare")
async def compare(req: Request):
    """Окно vs facts на сценарии сбора ТЗ (реальные вызовы LLM)."""
    data = await req.json() if req.headers.get("content-length") else {}
    filler = int(data.get("filler_turns", 8))
    res = run_compare(agent, filler_turns=filler, keep_last=KEEP_LAST)
    agent.set_context(STRATEGIES[MODE])     # вернуть активный режим после прогона
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

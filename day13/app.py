"""День 13 — веб-капот: агент с формализованным состоянием задачи (оркестратор + HITL).

Интерфейс показывает не «крути механизм кнопкой», а то, как работает реальный продукт
(по разбору преподавателя): дал задачу → оркестратор сам ведёт пайплайн по этапам, а на
переходах (если включён флаг) спрашивает человека «передавать дальше?». Человек одобряет
или вносит правку. Состояние персистится → паузу можно держать сколько угодно.

Запуск:
  uvicorn app:app --port 7860
  открыть http://localhost:7860
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from task_agent import TaskAgent
from task_state import TaskState

load_dotenv()

app = FastAPI()
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
INDEX_HTML = os.path.join(HERE, "index.html")
EXPLAINER_HTML = os.path.join(HERE, "explainer.html")
agent = TaskAgent()


def _state():
    return TaskState.load(STATE_FILE)


def _payload(state):
    snap = state.snapshot()
    snap["tokens"] = agent.ledger[-1]["cumulative"] if agent.ledger else 0
    return snap


class StartReq(BaseModel):
    goal: str
    ask_between: bool = True


class ReviseReq(BaseModel):
    note: str


class ToggleReq(BaseModel):
    ask_between: bool


@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX_HTML, encoding="utf-8") as f:
        return f.read()


@app.get("/explainer", response_class=HTMLResponse)
def explainer():
    with open(EXPLAINER_HTML, encoding="utf-8") as f:
        return f.read()


@app.get("/api/state")
def get_state():
    state = _state()
    return _payload(state) if state else {"empty": True}


@app.post("/api/start")
def start(req: StartReq):
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    agent.ledger = []
    state = TaskState(req.goal.strip(), path=STATE_FILE, ask_between=req.ask_between)
    state.save()
    agent.run_current(state)            # сразу выполняем первый этап (research)
    if not state.ask_between:           # режим «само» — гоним до конца
        agent.run_all(state)
    return _payload(state)


@app.post("/api/approve")
def approve():
    state = _state()
    if not state:
        return {"empty": True}
    agent.approve(state)
    return _payload(state)


@app.post("/api/revise")
def revise(req: ReviseReq):
    state = _state()
    if not state:
        return {"empty": True}
    agent.revise(state, req.note.strip())
    return _payload(state)


@app.post("/api/toggle")
def toggle(req: ToggleReq):
    state = _state()
    if not state:
        return {"empty": True}
    state.ask_between = req.ask_between
    state.save()
    return _payload(state)


@app.post("/api/reset")
def reset():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    agent.ledger = []
    return {"empty": True}

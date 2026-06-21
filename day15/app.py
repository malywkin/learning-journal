"""День 15 — веб-капот: ассистент с контролируемым жизненным циклом задачи.

Показывает не «крути кнопкой», а как работает контроль: рельсы (какие переходы есть) +
ВОРОТА (какие предусловия нужны на каждый переход) + рой валидаторов на проверке +
пауза/эскалация/resume. Состояние живёт на диске (state.json).

Запуск:  uvicorn app:app --port 7860   →   http://localhost:7860
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from gates import check_gate
from task_agent import TaskAgent
from task_state import ALLOWED, TaskState

load_dotenv()

app = FastAPI()
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
INDEX_HTML = os.path.join(HERE, "index.html")
agent = TaskAgent()


def _state():
    return TaskState.load(STATE_FILE)


def _payload(state):
    snap = state.snapshot()
    snap["tokens"] = agent.ledger[-1]["cumulative"] if agent.ledger else 0
    # ворота на каждый РАЗРЕШЁННЫЙ переход (рельсы) — главное, что показываем сверх Дня 13
    snap["gates"] = {to: check_gate(state, to) for to in state.snapshot()["next_allowed"]}
    snap["allowed_map"] = ALLOWED
    return snap


class StartReq(BaseModel):
    goal: str
    ask_between: bool = True


class ReviseReq(BaseModel):
    note: str


class ResolveReq(BaseModel):
    accept: bool


class TryReq(BaseModel):
    to: str


class ToggleReq(BaseModel):
    ask_between: bool


@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX_HTML, encoding="utf-8") as f:
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
    agent.run_current(state)                 # этап «План»
    if not state.ask_between:
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


@app.post("/api/resolve")
def resolve(req: ResolveReq):
    state = _state()
    if not state:
        return {"empty": True}
    agent.resolve(state, accept=req.accept)
    return _payload(state)


@app.post("/api/try")
def try_jump(req: TryReq):
    """ПОПРОБОВАТЬ переход, НЕ меняя состояние — для кнопок «недопустимый переход»."""
    state = _state()
    if not state:
        return {"empty": True}
    return agent.try_jump(state, req.to)


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

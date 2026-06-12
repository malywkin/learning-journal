"""День 9 — Агент со СЖАТИЕМ ИСТОРИИ: тонкий бэкенд (FastAPI).

«Провод» между страницей (index.html) и агентом (agent.py + compress.py + demos.py).
Демонстрирует ровно задание дня:
  • ЧАТ + КАПОТ — чат с тумблером «сжатие вкл/выкл»; справа в реальном времени видно,
    ЧТО уходит в модель: РОЛЬ + [КОПИЛКА summary] + ОКНО последних N реплик дословно,
    и сколько токенов это стоит (вход за ход) — payload не растёт лавиной;
  • СРАВНЕНИЕ — /api/compare: один диалог через три режима (без сжатия / сжатие+guardrail /
    сжатие наивное) → кто вспомнил спрятанный факт и сколько токенов потратил.

Запуск:
    .venv/bin/python app.py   →   http://127.0.0.1:8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from agent import Agent
from compress import NoCompression, RollingSummary
from demos import run_compare
from memory import JsonMemory
from tokens import estimate_messages, window_for

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = "Ты — вежливый помощник-ассистент. Отвечай кратко и по делу, на русском языке."
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")
KEEP_LAST = 4   # ОКНО: последние 4 реплики (≈2 хода) шлём дословно
TRIGGER = 6     # ПОТОЛОК: как несвёрнутых ≥6 — сворачиваем старое в копилку (мелко — чтобы в демо сработало быстро)

# Память на диске (наследие Дня 7) — чтобы рост истории был настоящим.
memory = JsonMemory(os.path.join(HERE, "memory.json"))
agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, memory=memory, name="Ассистент")

# Две стратегии контекста; на каждый ход выбираем по тумблеру с фронта.
PLAIN = NoCompression()
ROLL = RollingSummary(agent.make_summarizer(), keep_last=KEEP_LAST, trigger=TRIGGER)

app = FastAPI(title="Агент со сжатием истории — День 9")


def envelope():
    """Что РЕАЛЬНО ушло в модель на последнем ходу, разобранное на отсеки (для капота)."""
    sent = agent.last_sent or []
    view = ROLL.view()
    # роль = первый system; копилка = system со «Сводка…»; окно = всё остальное
    window = [m for m in sent if not (m["role"] == "system")]
    last = agent.ledger[-1] if agent.ledger else None
    return {
        "role_prompt": SYSTEM_PROMPT,
        "summary": view.get("summary", ""),
        "folded": view.get("folded", 0),
        "keep_last": KEEP_LAST,
        "trigger": TRIGGER,
        "window": window,
        "sent_count": len(sent),
        "input_tokens_real": (last or {}).get("usage", {}).get("prompt_tokens") if last else None,
        "input_estimate": estimate_messages(sent) if sent else None,
        "summarizations": view.get("summarizations", 0),
    }


def state():
    return {
        "model": MODEL,
        "window": window_for(MODEL),
        "keep_last": KEEP_LAST,
        "trigger": TRIGGER,
        "history": agent.history,        # ПОЛНАЯ история (на диске/в ОЗУ) — она всегда целая
        "ledger": agent.ledger,          # вход/выход по ходам (для «пилы»)
        "envelope": envelope(),          # что ушло в модель (роль/копилка/окно)
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
    compress = bool(data.get("compress"))
    # выбираем стратегию по тумблеру: сжатие или полная история
    agent.context = ROLL if compress else PLAIN
    reply = agent.send(user_msg)
    return JSONResponse({"reply": reply, "compress": compress, **state()})


@app.post("/api/clear")
def clear():
    agent.reset()
    # копилку тоже обнуляем (новая стратегия с тем же суммаризатором)
    global ROLL
    ROLL = RollingSummary(agent.make_summarizer(), keep_last=KEEP_LAST, trigger=TRIGGER)
    return JSONResponse(state())


@app.post("/api/compare")
async def compare(req: Request):
    """Сравнение без/со сжатия на скриптовом диалоге (реальные вызовы LLM)."""
    data = await req.json() if req.headers.get("content-length") else {}
    filler = int(data.get("filler_turns", 10))
    res = run_compare(agent, filler_turns=filler, keep_last=KEEP_LAST, trigger=10)
    return JSONResponse(res)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

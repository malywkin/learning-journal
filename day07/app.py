"""День 7 — Агент с памятью на диске: тонкий бэкенд (FastAPI).

Этот файл — «провод» между страницей (index.html) и агентом (agent.py), у которого
есть «папка дела» на диске (memory.py). Главная демонстрация дня:

  • при СТАРТЕ сервера агент загружает историю С ДИСКА (Agent(memory=...) → load());
  • страница показывает баннер «загружено N сообщений» — это и есть доказательство,
    что контекст пережил перезапуск;
  • панель «Память на диске» показывает РЕАЛЬНОЕ содержимое файла, прочитанное заново.

Как показать на видео:
  1) .venv/bin/python app.py  →  открыть http://127.0.0.1:8000
  2) поговорить (видно, как записи появляются в панели «на диске»);
  3) ОСТАНОВИТЬ сервер (Ctrl+C в терминале — видно в кадре) и запустить заново;
  4) обновить страницу → баннер «загружено N с диска», разговор на месте → продолжить.
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

from agent import Agent
from memory import JsonMemory, SqliteMemory

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

SYSTEM_PROMPT = (
    "Ты — вежливый помощник-ассистент. Отвечай кратко и по делу, на русском языке. "
    "Если чего-то не знаешь — честно скажи, не выдумывай."
)
MODEL = os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b:free")

store = "json"   # текущее хранилище: "json" или "sqlite"
agent = None


def build_agent(which):
    """(Пере)создать агента на выбранном хранилище. В конструкторе он СРАЗУ
    грузит историю с диска — поэтому рестарт сервера = продолжение разговора."""
    global store, agent
    store = which if which in ("json", "sqlite") else "json"
    if store == "json":
        mem = JsonMemory(os.path.join(HERE, "memory.json"))
    else:
        mem = SqliteMemory(os.path.join(HERE, "memory.db"))
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=MODEL, memory=mem, name="Ассистент")


build_agent("json")  # при запуске сервера поднимаем JSON-хранилище и грузим его с диска

app = FastAPI(title="Агент с памятью — День 7")


def state():
    """Полное состояние для страницы: что в истории + что лежит на диске."""
    return {
        "store": store,
        "history": agent.history,        # что разложено «на столе» (в памяти процесса)
        "loaded": len(agent.history),    # сколько сообщений поднято с диска
        "disk": agent.memory.raw_view(), # реальное содержимое файла, прочитанное заново
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
    reply = agent.send(user_msg)         # вся логика (вызов LLM + запись на диск) внутри
    return JSONResponse({"reply": reply, **state()})


@app.post("/api/store")
async def set_store(req: Request):
    """Переключить хранилище (JSON ↔ SQLite). Внимание: у каждого свой файл,
    поэтому история может отличаться — это разные «папки дела»."""
    data = await req.json()
    build_agent(data.get("store") or "json")
    return JSONResponse(state())


@app.post("/api/clear")
def clear():
    agent.reset()                        # стереть и в памяти, и на диске
    return JSONResponse(state())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

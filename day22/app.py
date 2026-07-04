"""
День 22 — веб-витрина (стеклянный ящик), :8220. Тонкий слой поверх rag_core:
задаёшь вопрос → два ответа бок о бок, под RAG видно найденные куски, ссылки и
собранный промпт. Отдельно — прогон 10 контрольных вопросов с метриками.

Тот же rag_core носит и CLI-сдачу (task22.py), и завтра — чат-продукт.
Запуск:  ../day21/.venv/bin/uvicorn app:app --port 8220
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import rag_core
from questions import GOLDEN
from task22 import grade

load_dotenv()
BASE = Path(__file__).parent
app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/api/ask")
def api_ask(q: str):
    """Один вопрос → оба режима сразу (для колонок бок о бок)."""
    plain = rag_core.plain_answer(q)
    rag = rag_core.rag_answer(q)
    return JSONResponse({"q": q, "plain": plain["answer"], "rag": rag})


@app.get("/api/golden")
def api_golden():
    """Прогон всех 10 контрольных вопросов (долго — много вызовов модели)."""
    rows = [grade(it) for it in GOLDEN]
    passed = sum(r["ok"] for r in rows)
    in_base = [r for r in rows if r["in_base"]]
    traps = [r for r in rows if not r["in_base"]]
    summary = {
        "passed": passed, "total": len(rows),
        "in_base_ok": sum(r["ok"] for r in in_base), "in_base_total": len(in_base),
        "trap_ok": sum(r["ok"] for r in traps), "trap_total": len(traps),
    }
    # чанки в ответе укорачиваем — таблице полный текст не нужен
    for r in rows:
        r.pop("citations", None)
    return JSONResponse({"rows": rows, "summary": summary})

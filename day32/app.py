"""
День 32 — локальное лицо AI-ревьюера (тонкий FastAPI). То же «окно в браузере, а не
терминал», что на Дне 31 (память prefers-gui-app-not-terminal), только вместо чата —
«положи diff → получи ревью». Мотор общий: здесь лишь HTTP и отдача страницы, вся
работа — в ai_review.py (контекст) и review_llm.py (запрос к модели).

Нужны fastapi + uvicorn (уже стоят в общем venv Дня 21).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import ai_review
import review_llm

BASE = Path(__file__).resolve().parent
app = FastAPI(title="AI-ревьюер кода — День 32")


class ReviewReq(BaseModel):
    diff: str = ""
    pr: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/sample")
def sample():
    """Отдать образец diff для кнопки «Загрузить образец»."""
    p = BASE / "sample_pr.diff"
    return JSONResponse({"diff": p.read_text(encoding="utf-8") if p.exists() else ""})


@app.post("/review")
def review(req: ReviewReq):
    """Прогнать ревью: diff из окна (или взять через gh по номеру PR) → контекст → модель."""
    diff = (req.diff or "").strip()
    if not diff and (req.pr or "").strip():
        try:
            diff = ai_review.diff_via_gh(req.pr.strip())
        except Exception as e:
            return JSONResponse({"error": f"не смог взять diff PR #{req.pr}: {e}"})
    if not diff:
        return JSONResponse({"error": "Пустой diff — вставь изменения или укажи номер PR."})

    files = ai_review.changed_files(diff)                       # изменённые файлы
    context = ai_review.gather_context(files)                   # правила проекта + код (RAG)
    data, provider = review_llm.ask_json(                       # запрос к модели (retry→fallback)
        ai_review.SYSTEM, ai_review.build_user(diff, context))
    if data is None:
        return JSONResponse({"error": "Модель недоступна после всех попыток (retry+fallback)."})

    data["_files"] = files
    data["_provider"] = provider
    return JSONResponse(data)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8320, log_level="warning")

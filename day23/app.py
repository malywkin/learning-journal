"""
День 23 — веб-демо «стеклянный ящик»: реранкинг вживую, поверх витрины Дня 22.

Продукт сверху (чат-ассистент по родительству), механика снизу: на один вопрос
две сборки бок о бок — «Было» (поиск Дня 22) и «Стало» (rewrite+rerank+порог).
Видно, как куски пересортировались по оценке реранкера и что отвалилось.

Запуск:  ../day21/.venv/bin/uvicorn app:app --port 8230
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / "day22" / ".env")  # ключ переиспользуем
load_dotenv(Path(__file__).parent / ".env")

import rag_plus  # noqa: E402

app = FastAPI(title="День 23 — Реранкинг и фильтрация")
BASE = Path(__file__).parent


class Query(BaseModel):
    question: str
    use_rewrite: bool = False
    top_k: int = 5
    threshold: float = 0.30


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.post("/compare")
def compare(q: Query):
    """Обе сборки на один вопрос — для колонок «Было» и «Стало»."""
    return rag_plus.compare(q.question, use_rewrite=q.use_rewrite,
                            top_k=q.top_k, threshold=q.threshold)


@app.get("/health")
def health():
    return {"ok": True, "has_key": bool(os.getenv("OPENROUTER_API_KEY"))}

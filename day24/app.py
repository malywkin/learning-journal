"""
День 24 — веб «стеклянный ящик»: цитаты, источники, анти-галлюцинации.

Продукт сверху (ассистент по родительству), механика снизу. На один вопрос показываем
ВЕСЬ конвейер с двумя предохранителями:
  ВХОД  — оценки реранкера с чертой порога: что прошло, что отвалилось, отказ ли;
  контракт — сырая тройка {answer, sources, quotes} от модели;
  ВЫХОД — проверка каждой цитаты КОДОМ (substring/fuzzy) + вердикт судьи (faithfulness).

Запуск:  ../day21/.venv/bin/uvicorn app:app --port 8240
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import grounded as g

app = FastAPI(title="День 24 — Цитаты и анти-галлюцинации")
BASE = Path(__file__).parent


class Query(BaseModel):
    question: str
    threshold: float = g.THRESHOLD
    judge: bool = True


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.post("/ask")
def ask(q: Query):
    """Полный конвейер Дня 24 на один вопрос — для стеклянного ящика."""
    return g.answer(q.question, threshold=q.threshold, judge=q.judge)


@app.get("/calibrate")
def calibrate():
    """10 вопросов golden set → top score реранкера + метка свой/ловушка.
    Тот самый разбор «где поставить порог» вживую (может занять ~15–20 с)."""
    import sys
    sys.path.insert(0, str(BASE.parent / "day22"))
    from questions import GOLDEN
    rows = []
    for item in GOLDEN:
        cand = g.retrieve(item["q"], k=g.CANDIDATES)
        graded = g.rerank_full(item["q"], cand, top_k=g.FINAL_K, threshold=0.0)
        rows.append({"q": item["q"], "in_base": item["in_base"],
                     "top": graded[0]["score"] if graded else 0.0})
    rows.sort(key=lambda r: r["top"], reverse=True)
    ins = [r["top"] for r in rows if r["in_base"]]
    traps = [r["top"] for r in rows if not r["in_base"]]
    gap = {"trap_max": max(traps), "in_min": min(ins),
           "suggest": round((max(traps) + min(ins)) / 2, 3) if min(ins) > max(traps) else None}
    return {"rows": rows, "gap": gap, "threshold": g.THRESHOLD}


@app.get("/health")
def health():
    return {"ok": True, "provider": g.PROVIDER, "model": g.MODEL}

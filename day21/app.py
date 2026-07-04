"""
День 21 — веб-витрина сдачи (стеклянный ящик).
Одна страница: чек-лист результата + живая нарезка двумя способами + поиск по книге.
Всё локально. Ученик открывает браузер и кликает — идеально под запись видео.
"""
import re
import struct
import sqlite3
from pathlib import Path

import sqlite_vec
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)

BASE = Path(__file__).parent
DB = BASE / "index.db"
import os
# Книга под копирайтом и лежит вне репозитория. Путь задаётся переменной окружения
# BOOK_PATH; по умолчанию ищем рядом со скриптом. В git книга НЕ входит.
BOOK = Path(os.getenv("BOOK_PATH", str(BASE / "Precious_Little_Sleep.md")))
SEC_START, SEC_END = 602, 797   # раздел Sleep Safety — для наглядной нарезки

print("Загружаю bge-m3…")
MODEL = SentenceTransformer("BAAI/bge-m3")
app = FastAPI()


def con():
    c = sqlite3.connect(DB)
    c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
    return c


def clean(text: str) -> str:
    text = re.sub(r"\[\[\d+\]\([^)]*\)\]", "", text)
    text = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\{\.smallcaps\}", r"\1", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"!?\[\]?\([^)]*\)", "", text)
    text = text.replace("\\#", "#").replace("\\", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def section_text():
    lines = BOOK.read_text(encoding="utf-8").splitlines()
    return clean("\n".join(lines[SEC_START - 1:SEC_END]))


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/api/summary")
def summary():
    c = con()
    total = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    blob = c.execute("SELECT embedding FROM vec_chunks LIMIT 1").fetchone()[0]
    vec = struct.unpack(f"{len(blob)//4}f", blob)
    meta = [dict(source=s, title=t, section=se, chunk_id=ci, strategy=st)
            for s, t, se, ci, st in c.execute(
            "SELECT source,title,section,chunk_id,strategy FROM chunks "
            "WHERE strategy='structural' LIMIT 3")]
    comp = {}
    for strat in ("fixed", "structural"):
        lens = [r[0] for r in c.execute(
            "SELECT length(text) FROM chunks WHERE strategy=?", (strat,))]
        comp[strat] = dict(count=len(lens), avg=sum(lens)//len(lens),
                           lo=min(lens), hi=max(lens))
    c.close()
    return dict(total=total, dim=len(vec), sample=[round(x, 3) for x in vec[:8]],
                db_kb=DB.stat().st_size // 1024, meta=meta, comp=comp)


@app.get("/api/slice")
def slice_():
    """Живая нарезка раздела Sleep Safety двумя способами — на честных настройках."""
    text = section_text()
    fixed = RecursiveCharacterTextSplitter(
        chunk_size=700, chunk_overlap=100, separators=["\n\n", "\n", " "])
    a = [dict(text=x.strip(), size=len(x)) for x in fixed.split_text(text)]
    md = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "h2"), ("###", "h3")])
    b = [dict(text=d.page_content.strip(), size=len(d.page_content),
              section=d.metadata.get("h3") or d.metadata.get("h2") or "—")
         for d in md.split_text(text) if d.page_content.strip()]
    return dict(fixed=a, structural=b)


@app.get("/api/search")
def search(q: str):
    emb = MODEL.encode([q], normalize_embeddings=True)[0].tolist()
    c = con()
    rows = c.execute("""
        SELECT c.section, c.text, v.distance
        FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH ? AND k = 12
        ORDER BY v.distance""", (sqlite_vec.serialize_float32(emb),)).fetchall()
    c.close()
    seen, out = set(), []
    for section, text, dist in rows:
        key = text[:60]
        if key in seen:
            continue
        seen.add(key)
        cos = round(1 - dist * dist / 2, 2)
        out.append(dict(section=section, cos=cos,
                        snippet=" ".join(text.split())[:260]))
        if len(out) == 4:
            break
    return JSONResponse(dict(q=q, results=out))

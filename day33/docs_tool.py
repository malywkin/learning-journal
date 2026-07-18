"""
День 31 — инструмент №1 роутера: ПОИСК ПО ДОКАМ проекта (наш RAG Дней 21–25).

Что переиспользуем (не с нуля):
  - нарезку markdown по заголовкам (day21/task21.py, chunk_structural — MarkdownHeaderTextSplitter);
  - схему индекса sqlite-vec + эмбеддер bge-m3 (day21);
  - формулу косинуса и чистку кусков (day22/rag_core.py).

Что нового (из брифа фронтира, чего не было на книге Дня 21):
  - индексируем МНОГО файлов (37 доков репо), в результате несём source (какой файл);
  - Contextual Retrieval (Anthropic, стандарт-2026): в эмбеддинг куска подмешиваем
    «путь › раздел», чтобы короткие доки (task.md) находились по смыслу, а не терялись;
  - большие разделы до-режем (бриф поправил миф «никогда не резать» — режем, если крупный).

Индекс лежит в config.INDEX_DB (day21/index.db не трогаем — там книга под копирайтом).
"""
import sqlite3
import sys
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

import config

# Реранкер Дня 23 (cross-encoder) — вторая ступень точности, чистый реюз.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "day23"))
from rerank import rerank  # noqa: E402

MAX_CHARS = 1200          # раздел крупнее — до-режем (бриф: большие резать можно)
_model = None


def _embedder() -> SentenceTransformer:
    """Ленивая загрузка эмбеддера (тяжёлый, грузим один раз) — приём Дня 22."""
    global _model
    if _model is None:
        _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


# ---------- 1. Нарезка одного markdown-файла (метод Дня 21) ----------
_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
)
_sub_splitter = RecursiveCharacterTextSplitter(
    chunk_size=MAX_CHARS, chunk_overlap=120, separators=["\n\n", "\n", " "]
)


def _chunk_file(relpath: str, text: str) -> list[dict]:
    """Файл → куски по заголовкам; крупные разделы до-режем. Раздел берём из метаданных."""
    out = []
    for d in _header_splitter.split_text(text):
        section = d.metadata.get("h3") or d.metadata.get("h2") or d.metadata.get("h1") or "—"
        body = d.page_content.strip()
        if not body:
            continue
        pieces = _sub_splitter.split_text(body) if len(body) > MAX_CHARS else [body]
        for p in pieces:
            out.append({"source": relpath, "section": section, "text": p.strip()})
    # Файл без заголовков (сплиттер вернул пусто) — кладём целиком/по размеру.
    if not out and text.strip():
        for p in _sub_splitter.split_text(text.strip()):
            out.append({"source": relpath, "section": "—", "text": p.strip()})
    return out


# ---------- 2. Построение индекса по всем докам ----------
def build_index(verbose: bool = True) -> int:
    """Собрать все доки под маску config.DOC_GLOBS → нарезать → эмбеддинги → sqlite-vec."""
    paths = config.docs_paths()
    rows = []
    for p in paths:
        rel = str(p.relative_to(config.REPO_ROOT))
        rows.extend(_chunk_file(rel, p.read_text(encoding="utf-8", errors="ignore")))
    if verbose:
        print(f"Доков: {len(paths)} → кусков: {len(rows)}")

    # Contextual Retrieval: в вектор подмешиваем «путь › раздел» + тело.
    to_embed = [f"{r['source']} › {r['section']}\n{r['text']}" for r in rows]
    if verbose:
        print(f"Считаю эмбеддинги {config.EMBED_MODEL} (один раз, ~минута)…")
    embs = _embedder().encode(to_embed, normalize_embeddings=True,
                              show_progress_bar=verbose, batch_size=16)
    dim = len(embs[0])

    db_path = config.INDEX_DB
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(str(db_path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    # Схема — как на Дне 21 (метаданные + виртуальная vec0, связь по rowid).
    db.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, source TEXT, section TEXT, text TEXT)")
    db.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])")
    for r, e in zip(rows, embs):
        cur = db.execute("INSERT INTO chunks(source, section, text) VALUES(?,?,?)",
                         (r["source"], r["section"], r["text"]))
        db.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES(?,?)",
                   (cur.lastrowid, sqlite_vec.serialize_float32(e.tolist())))
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    db.close()
    if verbose:
        print(f"Индекс готов: {db_path.name}, кусков в базе: {total}")
    return total


# ---------- 3a. Поиск-кандидаты (bi-encoder, широко и грубо — День 22) ----------
def _retrieve(query: str, n: int = 18) -> list[dict]:
    """Вопрос → n ближайших кусков по вектору. Быстро, но грубо: ступень для реранкера."""
    if not config.INDEX_DB.exists():
        build_index(verbose=False)
    qemb = _embedder().encode([query], normalize_embeddings=True)[0].tolist()
    db = sqlite3.connect(str(config.INDEX_DB))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    rows = db.execute(
        """SELECT c.source, c.section, c.text, v.distance
           FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
           WHERE v.embedding MATCH ? AND k = 30
           ORDER BY v.distance""",
        (sqlite_vec.serialize_float32(qemb),)).fetchall()
    db.close()
    seen, out = set(), []
    for source, section, text, dist in rows:
        key = (source, text[:60])
        if key in seen:
            continue
        seen.add(key)
        cos = round(1 - dist * dist / 2, 3)          # для нормализованных векторов (День 22)
        out.append({"source": source, "section": (section or "—").strip(" #"),
                    "text": " ".join(text.split()), "cos": cos})
        if len(out) == n:
            break
    return out


# ---------- 3b. Поиск по докам = кандидаты → реранк (инструмент роутера) ----------
def search_docs(query: str, k: int = 4) -> list[dict]:
    """Вопрос → k лучших кусков доков: поиск (День 22) + реранкер (День 23).
    Несём source (какой файл) для честной ссылки в ответе."""
    candidates = _retrieve(query, n=18)
    ranked = rerank(query, candidates, top_k=k, threshold=0.0)   # cross-encoder, score 0..1
    return ranked


if __name__ == "__main__":
    # Сборка индекса FAQ + смок-поиск (виден вклад реранкера: score, а не только cos).
    build_index()
    print("\n=== смок-поиск: 'почему не пускает вход через рабочую почту' ===")
    for r in search_docs("почему не пускает вход через рабочую почту", k=3):
        print(f"  score={r['score']} cos={r.get('cos')}  {r['source']} › {r['section']}: {r['text'][:80]}…")

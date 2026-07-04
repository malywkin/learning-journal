"""
День 21 — Индексация документов.
Пайплайн: главы книги → чистка → нарезка ДВУМЯ стратегиями → эмбеддинги (bge-m3)
→ локальный индекс sqlite-vec с метаданными (source, title, section, chunk_id + strategy).
В конце — сравнение двух стратегий нарезки.

Корпус: Precious Little Sleep (Alexis Dubief, 2020), главы 1–3 (~40 страниц).
Книга под копирайтом и личная — в git НЕ идёт, только этот код.
"""
import re
import sqlite3
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)

import os
# Книга под копирайтом, вне репозитория — путь через переменную окружения BOOK_PATH.
BOOK = Path(os.getenv("BOOK_PATH", str(Path(__file__).parent / "Precious_Little_Sleep.md")))
DB = Path(__file__).parent / "index.db"
TITLE = "Precious Little Sleep"
SOURCE = "Precious_Little_Sleep.md"
CH_START, CH_END = 469, 2074       # главы 1–3
MODEL = "BAAI/bge-m3"


# ---------- 1. Загрузка и чистка ----------
def load_and_clean() -> str:
    lines = BOOK.read_text(encoding="utf-8").splitlines()
    text = "\n".join(lines[CH_START - 1:CH_END])
    text = re.sub(r"\[\[\d+\]\([^)]*\)\]", "", text)             # сноски [[9](#notes...)]
    text = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", text)         # ссылки-заметки
    text = re.sub(r"\[([^\]]+)\]\{\.smallcaps\}", r"\1", text)   # [SWAP]{.smallcaps}
    text = re.sub(r"\{[^}]*\}", "", text)                         # {#...}/{.subtitle}
    text = re.sub(r"!?\[\]?\([^)]*\)", "", text)                  # картинки/пустые ссылки
    text = text.replace("\\#", "#").replace("\\", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def heading_map(text: str):
    """Список (позиция_в_тексте, заголовок) — чтобы для слепых чанков найти их раздел."""
    hs = []
    for m in re.finditer(r"^#{1,6}\s+(.+)$", text, flags=re.M):
        hs.append((m.start(), m.group(1).strip()))
    return hs


def section_at(pos: int, hmap) -> str:
    """Последний заголовок ДО позиции pos."""
    cur = "—"
    for off, h in hmap:
        if off <= pos:
            cur = h
        else:
            break
    return cur


# ---------- 2. Две стратегии нарезки ----------
def chunk_fixed(text: str, hmap):
    """Слепо по размеру: ~700 символов, нахлёст 100. Раздел вычисляем по позиции."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100,
                                              separators=["\n\n", "\n", " "])
    out = []
    cursor = 0
    for c in splitter.split_text(text):
        pos = text.find(c[:40], cursor)          # где начался чанк в исходнике
        if pos == -1:
            pos = cursor
        cursor = pos + 1
        out.append({"text": c.strip(), "section": section_at(pos, hmap)})
    return out


def chunk_structural(text: str):
    """Структурно по заголовкам markdown: раздел берём прямо из метаданных сплиттера."""
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
    )
    out = []
    for d in splitter.split_text(text):
        sec = d.metadata.get("h3") or d.metadata.get("h2") or d.metadata.get("h1") or "—"
        body = d.page_content.strip()
        if body:
            out.append({"text": body, "section": sec})
    return out


# ---------- 3. Индекс sqlite-vec ----------
def build_db(rows, dim):
    if DB.exists():
        DB.unlink()
    db = sqlite3.connect(DB)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    # метаданные — обычная таблица; векторы — виртуальная vec0; связь по rowid
    db.execute("""CREATE TABLE chunks(
        id INTEGER PRIMARY KEY, source TEXT, title TEXT,
        section TEXT, chunk_id INTEGER, strategy TEXT, text TEXT)""")
    db.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])")
    for r in rows:
        cur = db.execute(
            "INSERT INTO chunks(source,title,section,chunk_id,strategy,text) VALUES(?,?,?,?,?,?)",
            (SOURCE, TITLE, r["section"], r["chunk_id"], r["strategy"], r["text"]))
        db.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES(?,?)",
                   (cur.lastrowid, sqlite_vec.serialize_float32(r["emb"])))
    db.commit()
    return db


# ---------- 4. Сборка ----------
def main():
    print("Читаю и чищу главы 1–3…")
    text = load_and_clean()
    hmap = heading_map(text)
    words = len(text.split())
    print(f"  {len(text)} символов ≈ {words} слов ≈ {words // 250} страниц, заголовков: {len(hmap)}")

    fixed = chunk_fixed(text, hmap)
    struct = chunk_structural(text)
    for i, c in enumerate(fixed):
        c["strategy"], c["chunk_id"] = "fixed", i
    for i, c in enumerate(struct):
        c["strategy"], c["chunk_id"] = "structural", i
    print(f"Нарезка → слепо: {len(fixed)} чанков | структурно: {len(struct)} чанков")

    print(f"Загружаю {MODEL} и считаю эмбеддинги (это займёт минуту)…")
    model = SentenceTransformer(MODEL)
    rows = fixed + struct
    embs = model.encode([r["text"] for r in rows], normalize_embeddings=True,
                        show_progress_bar=True, batch_size=16)
    for r, e in zip(rows, embs):
        r["emb"] = e.tolist()
    dim = len(embs[0])

    print(f"Пишу индекс sqlite-vec (dim={dim})…")
    db = build_db(rows, dim)

    # ---------- Сравнение двух стратегий ----------
    def stats(name, cs):
        lens = [len(c["text"]) for c in cs]
        with_sec = sum(1 for c in cs if c["section"] != "—")
        return (f"{name:12} | чанков: {len(cs):3} | ср. размер: {sum(lens)//len(lens):4} симв. "
                f"| разброс: {min(lens)}–{max(lens)} | с разделом: {with_sec}/{len(cs)}")
    print("\n=== СРАВНЕНИЕ СТРАТЕГИЙ ===")
    print(stats("fixed", fixed))
    print(stats("structural", struct))
    total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"\nИндекс готов: {DB.name}, всего чанков в базе: {total}")
    db.close()


if __name__ == "__main__":
    main()

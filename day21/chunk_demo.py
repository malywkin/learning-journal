"""
День 21 — сцена «нарезка»: одна и та же глава книги, порезанная двумя способами.
Цель — увидеть глазами, где слепая нарезка рвёт мысль, а структурная держит её целой.
"""
import re
from pathlib import Path
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,      # «слепая» нарезка по размеру
    MarkdownHeaderTextSplitter,          # структурная нарезка по заголовкам
)

import os
# Книга под копирайтом, вне репозитория — путь через переменную окружения BOOK_PATH.
BOOK = Path(os.getenv("BOOK_PATH", str(Path(__file__).parent / "Precious_Little_Sleep.md")))
SECTION_START = 602   # ## Sleep Safety
SECTION_END = 797     # перед ## Where Should Your Baby Sleep?


def clean_pandoc(text: str) -> str:
    """Вычищаем технический мусор, оставшийся от конвертации EPUB→markdown."""
    text = re.sub(r"\[([^\]]+)\]\{\.smallcaps\}", r"\1", text)  # [ISBN]{.smallcaps} -> ISBN
    text = re.sub(r"\{#[^}]*\}", "", text)                       # {#chapter1.xhtml_...}
    text = re.sub(r"\{\.[^}]*\}", "", text)                      # {.subtitle}, {.chaptitle}
    text = re.sub(r"\{[^}]*\}", "", text)                        # прочие {...}
    text = re.sub(r"!\[\]\([^)]*\)", "", text)                   # картинки ![](...)
    text = re.sub(r"\[\]\([^)]*\)", "", text)                    # пустые ссылки
    text = text.replace("\\#", "#").replace("\\", "")            # экранирование pandoc
    text = re.sub(r"\n{3,}", "\n\n", text)                       # лишние пустые строки
    return text.strip()


# --- 1. Читаем нужный кусок книги и чистим ---
lines = BOOK.read_text(encoding="utf-8").splitlines()
raw = "\n".join(lines[SECTION_START - 1:SECTION_END])
before_len = len(raw)
section = clean_pandoc(raw)
print(f"Сырой кусок: {before_len} символов -> после чистки: {len(section)} символов")
print(f"(выкинули {before_len - len(section)} символов технического мусора)\n")

# --- 2. СПОСОБ А: слепая нарезка по размеру (~400 символов, без нахлёста) ---
fixed = RecursiveCharacterTextSplitter(
    chunk_size=400, chunk_overlap=0, separators=[" "]  # режем даже посреди абзаца
)
chunks_fixed = fixed.split_text(section)

# --- 3. СПОСОБ Б: структурная нарезка по заголовкам markdown ---
structural = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "chapter"), ("##", "section"), ("###", "subsection")]
)
chunks_struct = structural.split_text(section)


def preview(txt: str, n: int = 220) -> str:
    txt = txt.replace("\n", " ").strip()
    return (txt[:n] + " …") if len(txt) > n else txt


print("=" * 70)
print(f"СПОСОБ А — слепо по размеру: {len(chunks_fixed)} карточек")
print("=" * 70)
for i, c in enumerate(chunks_fixed[:4], 1):
    print(f"\n[A{i}] ({len(c)} симв.)  …{preview(c)}")
    print(f"      ↳ хвост: «…{c[-60:].strip()}»")

print("\n" + "=" * 70)
print(f"СПОСОБ Б — структурно по заголовкам: {len(chunks_struct)} карточек")
print("=" * 70)
for i, c in enumerate(chunks_struct[:6], 1):
    head = c.metadata.get("section") or c.metadata.get("chapter") or "—"
    print(f"\n[Б{i}] раздел: «{head}» ({len(c.page_content)} симв.)")
    print(f"      {preview(c.page_content)}")

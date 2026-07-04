"""
День 21 — сцена «Нарезка» для стеклянного ящика.
Берём один раздел книги, чистим, режем двумя способами и рисуем локальный HTML,
где карточки лежат рядом: слева слепая нарезка (рвёт мысль), справа структурная.
Текст книги остаётся ЛОКАЛЬНО — файл открывается в браузере у себя, никуда не уходит.
"""
import re
import json
import html
from pathlib import Path
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)

import os
# Книга под копирайтом, вне репозитория — путь через переменную окружения BOOK_PATH.
BOOK = Path(os.getenv("BOOK_PATH", str(Path(__file__).parent / "Precious_Little_Sleep.md")))
OUT = Path(__file__).parent / "scene_chunking.html"
SECTION_START, SECTION_END = 602, 797   # ## Sleep Safety


def clean(text: str) -> str:
    """Чистим технический мусор от конвертации EPUB→markdown, включая сноски."""
    text = re.sub(r"\[\[\d+\]\([^)]*\)\]", "", text)            # сноски [[9](#notes...)]
    text = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", text)        # ссылки-заметки [текст](#...)
    text = re.sub(r"\[([^\]]+)\]\{\.smallcaps\}", r"\1", text)  # [ISBN]{.smallcaps} -> ISBN
    text = re.sub(r"\{[^}]*\}", "", text)                        # {#...}, {.subtitle}
    text = re.sub(r"!\[\]\([^)]*\)", "", text)                   # картинки
    text = re.sub(r"\[\]\([^)]*\)", "", text)                    # пустые ссылки
    text = text.replace("\\#", "#").replace("\\", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


lines = BOOK.read_text(encoding="utf-8").splitlines()
raw = "\n".join(lines[SECTION_START - 1:SECTION_END])
section = clean(raw)
garbage = len(raw) - len(section)

# СПОСОБ А — слепо по размеру
fixed = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=0, separators=[" "])
chunks_a = fixed.split_text(section)

# СПОСОБ Б — структурно по заголовкам
md = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "chapter"), ("##", "section"), ("###", "subsection")]
)
chunks_b = md.split_text(section)


def torn_tail(txt):
    """Оборвана ли карточка на полуслове (для подсветки рваного края)."""
    t = txt.rstrip()
    return bool(t) and not t[-1] in ".!?:»\"'"


cards_a = [{"id": i + 1, "len": len(c), "text": c.strip(), "torn": torn_tail(c)}
           for i, c in enumerate(chunks_a)]
cards_b = [{"id": i + 1, "len": len(c.page_content),
            "section": c.metadata.get("section") or c.metadata.get("chapter") or "—",
            "text": c.page_content.strip()} for i, c in enumerate(chunks_b)]

data = {"garbage": garbage, "raw_len": len(raw), "clean_len": len(section),
        "a": cards_a, "b": cards_b}

HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>День 21 · Нарезка</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;padding:32px}
h1{font-size:22px;font-weight:600;margin-bottom:4px}
.sub{color:#8b949e;margin-bottom:24px;font-size:14px}
.bar{display:flex;gap:12px;margin-bottom:28px;flex-wrap:wrap}
.stat{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px 16px}
.stat b{font-size:20px;display:block;color:#58a6ff}
.stat.warn b{color:#e3b341}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:780px){.cols{grid-template-columns:1fr}}
.col h2{font-size:16px;margin-bottom:4px}
.col .hint{color:#8b949e;font-size:13px;margin-bottom:14px;min-height:34px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px 14px;margin-bottom:10px;
opacity:0;transform:translateY(8px);animation:in .4s forwards}
@keyframes in{to{opacity:1;transform:none}}
.card .meta{display:flex;justify-content:space-between;color:#8b949e;font-size:12px;margin-bottom:6px}
.card .txt{font-size:13.5px;color:#c9d1d9}
.a .card{border-left:3px solid #f85149}
.b .card{border-left:3px solid #3fb950}
.tag{background:#21262d;border-radius:5px;padding:1px 7px;font-size:11px}
.torn .txt::after{content:" ✂ …обрыв";color:#f85149;font-weight:600;font-size:12px}
.b .card .sec{color:#3fb950;font-weight:600;font-size:12px;margin-bottom:6px}
</style></head><body>
<h1>День 21 · Как режем книгу на карточки</h1>
<div class="sub">Раздел «Sleep Safety» из Precious Little Sleep — один и тот же текст, два способа нарезки.</div>
<div class="bar">
<div class="stat"><b>__RAW__</b>символов сырьё</div>
<div class="stat warn"><b>−__GARB__</b>вычищено мусора</div>
<div class="stat"><b>__NA__</b>карточек · слепо</div>
<div class="stat"><b>__NB__</b>карточек · структурно</div>
</div>
<div class="cols">
<div class="col a"><h2 style="color:#f85149">Слепо по размеру</h2>
<div class="hint">Режем каждые 400 символов, не глядя на смысл. Красный край — фраза оборвана на полуслове.</div>
<div id="a"></div></div>
<div class="col b"><h2 style="color:#3fb950">Структурно по заголовкам</h2>
<div class="hint">Режем по разделам книги. Каждая карточка — цельная мысль со своим заголовком.</div>
<div id="b"></div></div>
</div>
<script>
const D=__DATA__;
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
const a=document.getElementById('a');
D.a.forEach((c,i)=>{const el=document.createElement('div');el.className='card'+(c.torn?' torn':'');
el.style.animationDelay=(i*0.05)+'s';
el.innerHTML=`<div class="meta"><span class="tag">A${c.id}</span><span>${c.len} симв.</span></div><div class="txt">${esc(c.text)}</div>`;
a.appendChild(el)});
const b=document.getElementById('b');
D.b.forEach((c,i)=>{const el=document.createElement('div');el.className='card';
el.style.animationDelay=(0.3+i*0.12)+'s';
el.innerHTML=`<div class="sec">▸ ${esc(c.section)}</div><div class="meta"><span class="tag">Б${c.id}</span><span>${c.len} симв.</span></div><div class="txt">${esc(c.text)}</div>`;
b.appendChild(el)});
</script></body></html>"""

HTML = (HTML.replace("__RAW__", str(data["raw_len"]))
            .replace("__GARB__", str(data["garbage"]))
            .replace("__NA__", str(len(cards_a)))
            .replace("__NB__", str(len(cards_b)))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
OUT.write_text(HTML, encoding="utf-8")
print(f"Сцена готова: {OUT}")
print(f"Слепо: {len(cards_a)} карточек (рваных: {sum(c['torn'] for c in cards_a)}) | "
      f"Структурно: {len(cards_b)} карточек | мусора вычищено: {garbage} симв.")

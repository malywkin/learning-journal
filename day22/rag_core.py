"""
День 22 — ядро RAG-запроса (переиспользуемое; поверх индекса Дня 21).

Замыкаем петлю Дня 21: вопрос → ретривал ближайших чанков (День 21) → сборка
augmented-промпта → ответ модели со ссылками. Плюс второй режим «без RAG» для сравнения.

Это ядро НЕ привязано к экрану: и CLI-сдача (task22.py), и веб-витрина (app.py), и
будущий чат-продукт (ассистент по родительству) зовут одни и те же функции отсюда.

Защиты (из брифа фронтира, чего нет в лекции):
  - grounding: «отвечай только по источникам»;
  - abstain: «нет ответа — скажи "В источниках нет"» (иначе модель уверенно врёт);
  - валидация ссылок: [Источник N] с несуществующим N — выкидываем (грубый ловец липы).

Индекс и ключ переиспользуем из прошлых дней (не плодим заново):
  INDEX_DB     — путь к sqlite-vec индексу (по умолчанию day21/index.db)
  OPENROUTER_API_KEY — из .env
"""
import os
import re
import sqlite3
import time
from pathlib import Path

import sqlite_vec
from openai import OpenAI
from sentence_transformers import SentenceTransformer

BASE = Path(__file__).parent
# Индекс строили на Дне 21 — переиспользуем его, а не пересобираем.
INDEX_DB = Path(os.getenv("INDEX_DB", str(BASE.parent / "day21" / "index.db")))
EMBED_MODEL = "BAAI/bge-m3"                    # тот же эмбеддер, что в Дне 21
GEN_MODEL = "openai/gpt-oss-120b:free"         # 120b: 20b пустой content отдаёт (проверено)
REL_THRESHOLD = 0.5                            # ниже — считаем, что своего в базе нет

# Строгий системный промпт: три приказа — grounding + abstain + цитата.
SYSTEM = (
    "Ты — ассистент, отвечающий строго по приведённым источникам.\n"
    "Правила:\n"
    "1. Отвечай ТОЛЬКО по тексту источников ниже. Не добавляй знания из головы.\n"
    "2. Если ответа в источниках нет — ответь ровно: «В источниках нет.» и ничего больше.\n"
    "3. После утверждения ставь ссылку [Источник N] на конкретный кусок, откуда взял.\n"
    "Отвечай кратко и по-русски."
)

_model = None          # ленивая загрузка эмбеддера (тяжёлый, грузим один раз)
_client = None


def _embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _openrouter() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url="https://openrouter.ai/api/v1",
                         api_key=os.environ["OPENROUTER_API_KEY"], timeout=60)
    return _client


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(INDEX_DB))
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    return c


# ---------- 1. Ретривал (узел Дня 21) ----------
def retrieve(question: str, k: int = 4) -> list[dict]:
    """Вопрос → k ближайших по смыслу чанков. Возвращаем текст, раздел и близость.
    Чанки идут по убыванию близости → самый релевантный первым (узел «порядок»)."""
    qemb = _embedder().encode([question], normalize_embeddings=True)[0].tolist()
    db = _db()
    rows = db.execute(
        """SELECT c.section, c.text, v.distance
           FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
           WHERE v.embedding MATCH ? AND k = 20
           ORDER BY v.distance""",
        (sqlite_vec.serialize_float32(qemb),)).fetchall()
    db.close()
    seen, out = set(), []
    for section, text, dist in rows:
        key = text[:60]
        if key in seen:                       # структурная нарезка Дня 21 давала дубли
            continue
        seen.add(key)
        text = " ".join(text.split())         # чистим мусорные переносы/пробелы
        cos = round(1 - dist * dist / 2, 3)   # для нормализованных векторов
        out.append({"section": section.strip(" #"), "text": text, "cos": cos})
        if len(out) == k:
            break
    return out


# ---------- 2. Сборка augmented-промпта (узел дня) ----------
def build_context(chunks: list[dict], limit: int = 500) -> str:
    """Куски → пронумерованный контекст с метками источника и раздела."""
    return "\n\n".join(
        f"[Источник {i + 1}] (раздел: {c['section']})\n{c['text'][:limit]}"
        for i, c in enumerate(chunks))


# ---------- 3. Вызов модели (устойчивый к 429 free-тарифа) ----------
def _ask(messages, max_tokens=260, tries=6) -> str:
    """Free-модели часто отдают 429 — ретраим с паузой (память openrouter-free-tier)."""
    last = ""
    for attempt in range(tries):
        try:
            r = _openrouter().chat.completions.create(
                model=GEN_MODEL, temperature=0, max_tokens=max_tokens, messages=messages)
            content = (r.choices[0].message.content or "").strip()
            if content:
                return content
            last = "(модель вернула пустой ответ)"
        except Exception as e:                # 429 и прочее
            last = f"(ошибка вызова: {type(e).__name__})"
        time.sleep(4)
    return last


# ---------- 4. Валидация ссылок (нижняя ступень защиты из узла 5) ----------
def validate_citations(answer: str, n_chunks: int) -> dict:
    """Достаём [Источник N] из ответа, ловим номера вне диапазона (выдуманные)."""
    nums = [int(n) for n in re.findall(r"\[Источник\s*(\d+)\]", answer)]
    valid = sorted({n for n in nums if 1 <= n <= n_chunks})
    invalid = sorted({n for n in nums if n < 1 or n > n_chunks})
    return {"cited": sorted(set(nums)), "valid": valid, "invalid": invalid}


# ---------- 5. Два режима: без RAG и с RAG ----------
def plain_answer(question: str) -> dict:
    """Без RAG: голый вопрос, модель отвечает из головы (обучающие данные)."""
    ans = _ask([{"role": "user", "content": question}], max_tokens=260)
    return {"mode": "plain", "answer": ans}


def rag_answer(question: str, k: int = 4) -> dict:
    """С RAG: ретривал → augmented-промпт → ответ со ссылками + разбор.
    Это и есть переиспользуемое ядро будущего чат-продукта."""
    chunks = retrieve(question, k=k)
    top_cos = chunks[0]["cos"] if chunks else 0.0
    context = build_context(chunks)
    user = f"ИСТОЧНИКИ:\n{context}\n\nВОПРОС: {question}\nОТВЕТ:"
    ans = _ask([{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user}], max_tokens=260)
    abstained = "в источниках нет" in ans.lower()
    return {
        "mode": "rag",
        "answer": ans,
        "chunks": chunks,
        "top_cos": top_cos,
        "abstained": abstained,
        "citations": validate_citations(ans, len(chunks)),
        "prompt_preview": user,
    }

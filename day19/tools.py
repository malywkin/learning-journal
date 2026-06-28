"""
День 19 — три «работы», из которых собирается цепочка search → summarize → save_to_file.

Здесь НЕТ ни MCP, ни оркестратора — только три функции, понятные сами по себе. Каждая
принимает простые данные и возвращает ТИПИЗИРОВАННЫЙ словарь (а не сырой текст). Это
важно для дня: выход одного шага = вход следующего, и чтобы передача была надёжной,
шаги договариваются формой данных (контрактом), а не парсингом строк.

  • search_reddit(...)   — ПОЛУЧАЕТ данные: сходить в Reddit (твой arctic / Arctic Shift),
    вернуть компактный список постов (заголовок + счётчики). «Компактный» нарочно: так его
    не страшно прогнать даже через модель в режиме агента (антипаттерн из брифа — гонять
    тяжёлый сырой текст между инструментами).
  • summarize_posts(...) — ОБРАБАТЫВАЕТ: свернуть посты LLM в короткую сводку. Ограничитель
    против выдумок (temp 0, запрет придумывать, короткий потолок) — как в Днях 9–12, 18.
  • save_to_file(...)    — СОХРАНЯЕТ: записать готовую сводку в файл, вернуть путь и размер.
"""

import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

# Бесплатные модели OpenRouter часто отдают 429 (rate-limit) — короткие ретраи с backoff.
_RETRY_429 = 4

import arctic  # вендорная копия твоего reddit-клиента (Arctic Shift, без ключей)

load_dotenv()

HERE = Path(__file__).parent
OUT_DIR = HERE / "output"  # сюда save_to_file кладёт файлы (внутри папки дня)

SUMMARY_MODEL = "openai/gpt-oss-120b:free"  # 120b ровнее держит формат, чем 20b


# ---------- ШАГ 1: ПОЛУЧИТЬ данные ----------

def _trim(p: dict) -> dict:
    """Оставить от поста только лёгкое: заголовок + счётчики. Без тела — чтобы цепочка
    передавала компактные данные, а не мегабайты текста (бриф: не гонять сырьё через модель)."""
    return {
        "title": p.get("title") or "",
        "score": p.get("score") or 0,
        "num_comments": p.get("num_comments") or 0,
        "permalink": p.get("permalink") or "",
    }


def search_reddit(subreddit: str, query: str = "", limit: int = 15) -> dict:
    """Найти свежие посты в r/<subreddit> (опц. по слову query). Вернуть компактный список.

    Возвращает типизированный результат — это и есть контракт выхода шага 1:
      {ok, subreddit, query, count, posts:[{title, score, num_comments, permalink}]}
    """
    try:
        raw = arctic.search_posts(
            subreddit=subreddit,
            query=query or None,
            sort="desc",
            limit=limit,
        )
    except Exception as e:  # чужой архив может тормозить/лежать — не роняем цепочку
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "subreddit": subreddit, "query": query, "count": 0, "posts": []}

    posts = [_trim(p) for p in raw if p.get("title")]
    return {"ok": True, "subreddit": subreddit, "query": query,
            "count": len(posts), "posts": posts}


# ---------- ШАГ 2: ОБРАБОТАТЬ (LLM-сводка) ----------

def _llm() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=90,  # без таймаута зависший free-провайдер вешает весь запрос
    )


def summarize_posts(posts: list[dict], subreddit: str = "") -> dict:
    """Свернуть посты (выход шага 1) в короткую сводку «что нового».

    Принимает РОВНО то, что вернул search_reddit — список постов. Это и есть «передача
    данных между инструментами»: вход шага 2 = выход шага 1.
    Возвращает: {ok, n_posts, summary, subreddit}.
    """
    if not posts:
        return {"ok": False, "error": "пустой вход: нечего сворачивать",
                "n_posts": 0, "summary": "", "subreddit": subreddit}

    titles = "\n".join(
        f"- {p.get('title','')} (score {p.get('score',0)}, {p.get('num_comments',0)} комм.)"
        for p in posts
    )
    system = (
        "Ты делаешь короткий дайджест по заголовкам постов Reddit. Пиши по-русски, "
        "3–5 пунктов, только по тому, что есть в списке. НИЧЕГО не придумывай: не добавляй "
        "фактов, имён и цифр, которых нет во входе. Без вступлений и воды."
    )
    where = f"r/{subreddit}" if subreddit else "Reddit"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Посты из {where}:\n{titles}\n\nСделай дайджест «что нового»."},
    ]
    delay = 2
    for attempt in range(_RETRY_429):
        try:
            resp = _llm().chat.completions.create(
                model=SUMMARY_MODEL,
                messages=messages,
                temperature=0,
                max_tokens=450,
                extra_body={"reasoning": {"effort": "low"}},
            )
            summary = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)  # честный серверный счёт (как День 8)
            break
        except APIStatusError as e:
            if e.status_code == 429 and attempt < _RETRY_429 - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return {"ok": False, "error": f"LLM {e.status_code}",
                    "n_posts": len(posts), "summary": "", "subreddit": subreddit, "tokens": 0}

    return {"ok": True, "n_posts": len(posts), "summary": summary, "subreddit": subreddit,
            "tokens": tokens}


# ---------- ШАГ 3: СОХРАНИТЬ результат ----------

def _safe_name(name: str) -> str:
    """Обезвредить имя файла: только буквы/цифры/._-; не дать вылезти из папки output."""
    base = os.path.basename(name.strip())
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base) or "digest"
    if not base.endswith(".md") and not base.endswith(".txt"):
        base += ".md"
    return base


def save_to_file(content: str, filename: str = "") -> dict:
    """Записать готовую сводку (выход шага 2) в файл внутри output/. Вернуть путь и размер.

    Возвращает: {ok, path, filename, bytes}.
    """
    if not content or not content.strip():
        return {"ok": False, "error": "пустой контент: нечего сохранять", "path": "", "bytes": 0}

    OUT_DIR.mkdir(exist_ok=True)
    fname = _safe_name(filename or f"digest_{int(time.time())}")
    path = OUT_DIR / fname
    data = content.strip() + "\n"
    path.write_text(data, encoding="utf-8")
    return {"ok": True, "path": str(path), "filename": fname, "bytes": len(data.encode("utf-8"))}

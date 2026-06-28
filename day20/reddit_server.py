"""
День 20 — СЕРВЕР №1 «reddit». Одна из трёх стоек.

Что он умеет (его инструменты):
  • search_reddit(subreddit, query, limit) — найти свежие посты;
  • summarize_posts(posts, subreddit)      — свернуть найденное в короткий дайджест (по-английски).

Куда «подключается» этот сервер: НАРУЖУ, на reddit.com (через вендорный arctic.py / Arctic
Shift), а для сводки — к OpenRouter. Но это его ВНУТРЕННЯЯ кухня. Для агента он просто стойка
с двумя инструментами. Сравни с utils-сервером, который не ходит вообще никуда.

Слушает 127.0.0.1:8101, транспорт Streamable HTTP (SSE устарел — бриф Дня 20).
Сводку держим по-английски НАРОЧНО: дальше по флоу utils-сервер переведёт её на русский —
так в одном задании участвуют разные серверы (reddit → utils → storage).
"""

import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import arctic  # вендорная копия reddit-клиента (Arctic Shift, без ключей)
import llm


# ---------- типизированные контракты выхода (→ outputSchema + structuredContent) ----------
# Голый -> dict у FastMCP контракта НЕ даёт (проверено в Дне 19): structuredContent пуст,
# данные уходят сырым текстом. Поэтому форму ответа объявляем Pydantic-моделью.

class Post(BaseModel):
    title: str = ""
    score: int = 0
    num_comments: int = 0
    permalink: str = ""


class SearchResult(BaseModel):
    ok: bool
    subreddit: str = ""
    query: str = ""
    count: int = 0
    posts: list[Post] = Field(default_factory=list)
    error: str = ""


class SummaryResult(BaseModel):
    ok: bool
    n_posts: int = 0
    summary: str = ""
    subreddit: str = ""
    tokens: int = 0
    error: str = ""


mcp = FastMCP("reddit", host="127.0.0.1", port=8101)


def _trim(p: dict) -> dict:
    """Оставить от поста только лёгкое: заголовок + счётчики (не гнать мегабайты через модель)."""
    return {
        "title": p.get("title") or "",
        "score": p.get("score") or 0,
        "num_comments": p.get("num_comments") or 0,
        "permalink": p.get("permalink") or "",
    }


@mcp.tool(annotations=ToolAnnotations(title="Поиск постов в Reddit", readOnlyHint=True))
def search_reddit(subreddit: str, query: str = "", limit: int = 15) -> SearchResult:
    """Найти свежие посты в r/<subreddit> (опц. по слову query). Это вход всей цепочки.
    Возвращает компактный список: {ok, subreddit, query, count, posts:[...]}."""
    try:
        raw = arctic.search_posts(subreddit=subreddit, query=query or None, sort="desc", limit=limit)
    except Exception as e:  # чужой архив может лежать — не роняем флоу
        return SearchResult(ok=False, error=f"{type(e).__name__}: {e}",
                            subreddit=subreddit, query=query)
    posts = [_trim(p) for p in raw if p.get("title")]
    return SearchResult(ok=True, subreddit=subreddit, query=query, count=len(posts),
                        posts=[Post(**p) for p in posts])


@mcp.tool(annotations=ToolAnnotations(title="Сводка по постам (LLM)", readOnlyHint=True))
def summarize_posts(posts: list[Post], subreddit: str = "") -> SummaryResult:
    """Свернуть НАЙДЕННЫЕ посты (выход search_reddit) в короткий дайджест по-английски.
    На вход — РОВНО список posts из результата search_reddit. Возвращает {ok, summary, ...}."""
    if not posts:
        return SummaryResult(ok=False, error="пустой вход: нечего сворачивать", subreddit=subreddit)

    titles = "\n".join(
        f"- {p.title} (score {p.score}, {p.num_comments} comments)" for p in posts
    )
    where = f"r/{subreddit}" if subreddit else "Reddit"
    messages = [
        {"role": "system", "content": (
            "You write a short digest of Reddit post titles. Output 3-5 bullet points in "
            "ENGLISH, strictly from the given list. Invent NOTHING: no facts, names or numbers "
            "that are not in the input. No preamble, no fluff."
        )},
        {"role": "user", "content": f"Posts from {where}:\n{titles}\n\nWrite a 'what's new' digest."},
    ]
    try:
        resp = llm.chat_with_retry(
            model=llm.MODEL, messages=messages, temperature=0, max_tokens=450,
            extra_body={"reasoning": {"effort": "low"}},
        )
    except Exception as e:
        return SummaryResult(ok=False, error=f"LLM: {type(e).__name__}", n_posts=len(posts),
                             subreddit=subreddit)
    summary = (resp.choices[0].message.content or "").strip()
    tokens = int(getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0)
    return SummaryResult(ok=True, n_posts=len(posts), summary=summary, subreddit=subreddit,
                         tokens=tokens)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

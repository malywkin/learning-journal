"""
День 19 — НАШ MCP-сервер с тремя инструментами, из которых собирается цепочка.

Связь с прошлым:
  • День 17 — один инструмент + агент, который САМ решает его позвать (tool_choice=auto).
  • День 18 — инструменты, которые ставят фоновую работу на расписание.
  • День 19 — НЕСКОЛЬКО инструментов, которые СОЕДИНЯЮТСЯ в цепочку: search → summarize →
    save_to_file. Выход одного = вход следующего.

Главное «под капотом» (бриф): в самом протоколе MCP НЕТ вызова инструмента из инструмента
и нет понятия «цепочка». Сервер лишь предлагает три отдельных инструмента — а порядок
задаёт ОРКЕСТРАТОР снаружи: либо наш код (жёсткий пайплайн, pipeline.py), либо модель
(агент, agent.py). Сервер у обоих один и тот же.

ТИПИЗИРОВАННЫЙ КОНТРАКТ между шагами (важный момент дня):
Сначала инструменты возвращали голый `dict` — и сервер отдавал данные как СЫРОЙ ТЕКСТ
(structuredContent был пуст, outputSchema отсутствовал). Проверено вживую. Чтобы выход
стал машиночитаемым (как требует задание — «корректность передачи данных»), форму ответа
надо ОБЪЯВИТЬ: возвращаем Pydantic-модель → FastMCP выводит из неё outputSchema и кладёт
данные в structuredContent. Теперь следующий шаг берёт поля по имени (r["posts"]), а не
парсит строку. Это и есть контракт выхода инструмента (спека MCP 2025-06-18: outputSchema
+ structuredContent).

Транспорт — Streamable HTTP, слушаем только 127.0.0.1.  Запуск:  python mcp_server.py
"""

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import tools


# ---------- типизированные контракты выхода (→ outputSchema + structuredContent) ----------

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
    tokens: int = 0          # сколько токенов сожрала сама сводка (работа модели)
    error: str = ""


class SaveResult(BaseModel):
    ok: bool
    path: str = ""
    filename: str = ""
    bytes: int = 0
    error: str = ""


mcp = FastMCP("reddit-pipeline-day19", host="127.0.0.1", port=8029)


@mcp.tool(annotations=ToolAnnotations(title="Поиск постов в Reddit", readOnlyHint=True))
def search(subreddit: str, query: str = "", limit: int = 15) -> SearchResult:
    """ШАГ 1 — ПОЛУЧИТЬ данные. Найти свежие посты в r/<subreddit> (опц. по слову query).
    Возвращает компактный список постов: {ok, subreddit, query, count, posts:[...]}."""
    return SearchResult(**tools.search_reddit(subreddit=subreddit, query=query, limit=limit))


@mcp.tool(annotations=ToolAnnotations(title="Сводка по постам (LLM)", readOnlyHint=True))
def summarize(posts: list[Post], subreddit: str = "") -> SummaryResult:
    """ШАГ 2 — ОБРАБОТАТЬ. Свернуть посты (выход шага search) в короткую сводку «что нового».
    На вход подаётся РОВНО список posts из результата search. Возвращает {ok, n_posts, summary}."""
    plain = [p.model_dump() for p in posts]
    return SummaryResult(**tools.summarize_posts(posts=plain, subreddit=subreddit))


@mcp.tool(annotations=ToolAnnotations(title="Сохранить в файл", readOnlyHint=False))
def save_to_file(content: str, filename: str = "") -> SaveResult:
    """ШАГ 3 — СОХРАНИТЬ. Записать готовую сводку (выход шага summarize) в файл.
    Это единственный инструмент, который ПИШЕТ (readOnlyHint=False) → агент спросит
    подтверждение перед вызовом. Возвращает {ok, path, filename, bytes}."""
    return SaveResult(**tools.save_to_file(content=content, filename=filename))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

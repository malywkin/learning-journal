"""
День 19 — ЖЁСТКИЙ ПАЙПЛАЙН: порядок инструментов задаёт КОД, а не модель.

Это буквальный ответ на задание: «первый получает данные, второй обрабатывает, третий
сохраняет». Здесь оркестратор — обычный Python: он сам зовёт три MCP-инструмента строго
по порядку и РУКАМИ передаёт выход одного на вход следующего.

Почему так, а не агент (бриф, методичка Anthropic «Building Effective Agents»): если шаг B
требует выход A, а C — выход B, это по определению ПАЙПЛАЙН, и для него прошитый порядок
проще, дешевле и предсказуемее оркестратора-модели. Модель тут ничего не «решает» — решать
нечего, путь известен заранее. Единственный вызов LLM во всей цепочке — внутри summarize.

Передача данных типизирована: search возвращает structuredContent (поле posts), и мы берём
r1["posts"] по имени, а не парсим текст. Ошибка на любом шаге останавливает цепочку (выход
сломанного шага нельзя подавать дальше).
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = "http://127.0.0.1:8029/mcp"

# Канонические шаги цепочки: (имя MCP-инструмента, что он делает).
STEPS = [
    ("search", "ПОЛУЧИТЬ данные"),
    ("summarize", "ОБРАБОТАТЬ (LLM)"),
    ("save_to_file", "СОХРАНИТЬ результат"),
]


async def _call(session: ClientSession, name: str, args: dict) -> dict:
    """Позвать MCP-инструмент и вернуть его типизированный результат (structuredContent).
    Фолбэк — разобрать JSON из текстового content, если сервер не отдал structuredContent."""
    res = await session.call_tool(name, args)
    if res.structuredContent:
        # FastMCP оборачивает примитивы в {"result": ...}; объект-модель отдаёт как есть
        sc = res.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    if res.content and getattr(res.content[0], "text", None):
        import json
        try:
            return json.loads(res.content[0].text)
        except json.JSONDecodeError:
            return {"ok": False, "error": "не разобрать ответ инструмента"}
    return {"ok": False, "error": "пустой ответ инструмента"}


async def run_pipeline(subreddit: str, query: str = "", limit: int = 15,
                       filename: str = "") -> dict:
    """Прогнать цепочку search → summarize → save_to_file. Вернуть трассу для витрины."""
    trace: list[dict] = []

    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # --- ШАГ 1: search --- вход задаём мы
            in1 = {"subreddit": subreddit, "query": query, "limit": limit}
            r1 = await _call(session, "search", in1)
            trace.append({
                "step": "search", "role": "ПОЛУЧИТЬ данные",
                "input": in1, "ok": r1.get("ok", False),
                "output": r1,
                "result_line": (f'нашёл постов: {r1.get("count", 0)}'
                                if r1.get("ok") else f'ошибка: {r1.get("error")}'),
                "handoff": f'посты ({r1.get("count", 0)} шт.) → summarize',
            })
            if not r1.get("ok") or not r1.get("posts"):
                return _stop(trace, "search", llm_calls=0)

            # --- ШАГ 2: summarize --- ВХОД = ВЫХОД ШАГА 1 (передаём posts явно)
            in2 = {"posts": r1["posts"], "subreddit": r1.get("subreddit", subreddit)}
            r2 = await _call(session, "summarize", in2)
            work_calls = 1  # внутри summarize модель позвана один раз (это «работа»)
            work_tokens = int(r2.get("tokens", 0) or 0)
            trace.append({
                "step": "summarize", "role": "ОБРАБОТАТЬ (LLM)",
                "input": {"posts": f'[{len(r1["posts"])} постов из шага search]',
                          "subreddit": in2["subreddit"]},
                "ok": r2.get("ok", False),
                "output": r2,
                "result_line": (f'сводка готова ({len(r2.get("summary", ""))} симв.)'
                                if r2.get("ok") else f'ошибка: {r2.get("error")}'),
                "handoff": "summary (текст) → save_to_file",
            })
            if not r2.get("ok") or not r2.get("summary"):
                return _stop(trace, "summarize", work_calls=work_calls, work_tokens=work_tokens)

            # --- ШАГ 3: save_to_file --- ВХОД = ВЫХОД ШАГА 2 (передаём summary явно)
            fname = filename or f"{subreddit}_digest"
            in3 = {"content": r2["summary"], "filename": fname}
            r3 = await _call(session, "save_to_file", in3)
            trace.append({
                "step": "save_to_file", "role": "СОХРАНИТЬ результат",
                "input": {"content": f'[сводка из шага summarize, {len(r2["summary"])} симв.]',
                          "filename": fname},
                "ok": r3.get("ok", False),
                "output": r3,
                "result_line": (f'записано: {r3.get("filename")} ({r3.get("bytes", 0)} байт)'
                                if r3.get("ok") else f'ошибка: {r3.get("error")}'),
                "handoff": "",
            })

            return {
                "ok": r3.get("ok", False),
                "mode": "pipeline",
                "trace": trace,
                # два РАЗНЫХ вида похода к модели — чтобы сравнение с агентом было честным:
                "work_calls": work_calls,   # модель делает контент (сводку) — 1 раз
                "steering_calls": 0,        # модель выбирает порядок — НИ разу (порядок в коде)
                "llm_calls": work_calls,    # всего походов к модели = work + steering
                "routing_decisions": 0,
                # токены (честный серверный usage): у пайплайна весь расход — это работа сводки
                "work_tokens": work_tokens,
                "steering_tokens": 0,
                "total_tokens": work_tokens,
                "summary": r2.get("summary", ""),
                "file_path": r3.get("path", ""),
            }


def _stop(trace: list[dict], where: str, work_calls: int = 0, work_tokens: int = 0) -> dict:
    """Цепочка остановлена на шаге where: сломанный выход нельзя подавать дальше."""
    return {"ok": False, "mode": "pipeline", "trace": trace,
            "work_calls": work_calls, "steering_calls": 0, "llm_calls": work_calls,
            "routing_decisions": 0,
            "work_tokens": work_tokens, "steering_tokens": 0, "total_tokens": work_tokens,
            "stopped_at": where, "summary": "", "file_path": ""}


if __name__ == "__main__":
    import json
    import sys
    sub = sys.argv[1] if len(sys.argv) > 1 else "LocalLLaMA"
    q = sys.argv[2] if len(sys.argv) > 2 else ""
    out = asyncio.run(run_pipeline(sub, q))
    print(json.dumps(out, ensure_ascii=False, indent=2))

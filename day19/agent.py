"""
День 19 — АГЕНТ-ОРКЕСТРАТОР: порядок инструментов выбирает МОДЕЛЬ (tool_choice=auto).

Тот же приём, что в Дне 17 (модель сама решает, какой инструмент позвать), только теперь
инструментов три и модель должна выстроить из них цепочку САМА: получить задачу «найди →
сверни → сохрани», понять, что сперва search, потом summarize по найденному, потом
save_to_file по сводке.

Сервер — тот же самый (mcp_server.py). Разница с pipeline.py только в оркестраторе:
там порядок вёл код, тут — модель в цикле. Поэтому здесь видна цена гибкости (бриф):
каждый ход — отдельный вызов LLM (а не один, как в пайплайне), и модель может ошибиться
с порядком или потерять данные между шагами.

Считаем две величины для честного сравнения с пайплайном:
  • llm_calls       — сколько РАЗ позвали модель (в пайплайне — 1);
  • routing_decisions — сколько раз модель ВЫБИРАЛА инструмент (в пайплайне — 0).
"""

import json
import os
import time

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

MCP_URL = "http://127.0.0.1:8029/mcp"
MODEL = "openai/gpt-oss-120b:free"  # 20b на "auto" инструмент не зовёт — проверено в Дне 17

SYSTEM = (
    "Ты ассистент, который умеет работать с Reddit через инструменты. Тебе дают задачу, "
    "и ты выполняешь её ЦЕПОЧКОЙ вызовов инструментов, по одному за раз. Доступны:\n"
    "  • search(subreddit, query, limit) — найти посты;\n"
    "  • summarize(posts, subreddit) — свернуть НАЙДЕННЫЕ посты в сводку;\n"
    "  • save_to_file(content, filename) — сохранить готовую сводку в файл.\n"
    "Правила: сперва search; затем передай поле posts из его результата в summarize; "
    "затем передай поле summary из результата summarize в save_to_file как content. "
    "Не выдумывай посты — бери их только из результата search. Когда файл сохранён — "
    "кратко ответь по-русски, что сделано."
)

ROLE = {
    "search": "ПОЛУЧИТЬ данные",
    "summarize": "ОБРАБОТАТЬ (LLM)",
    "save_to_file": "СОХРАНИТЬ результат",
}


def _client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=90,
    )


def _llm_with_retry(client: OpenAI, **kwargs):
    """Вызов модели с короткими ретраями на 429 (free-tier любит rate-limit)."""
    delay = 2
    for attempt in range(4):
        try:
            return client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            if e.status_code == 429 and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def _mcp_tools_to_openai(tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _structured(call) -> dict:
    if call.structuredContent:
        sc = call.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    if call.content and getattr(call.content[0], "text", None):
        try:
            return json.loads(call.content[0].text)
        except json.JSONDecodeError:
            return {"text": call.content[0].text}
    return {}


async def run_agent(subreddit: str, query: str = "", filename: str = "",
                    on_confirm=None) -> dict:
    """Дать агенту задачу и дать ему самому собрать цепочку. Вернуть трассу для витрины.

    on_confirm(name, args)->bool — человек-в-цикле на запись (как в Дне 17). Если None —
    запись подтверждается автоматически (для веб-демо).
    """
    fname = filename or f"{subreddit}_digest"
    task = (f"Найди свежие посты в r/{subreddit}"
            + (f" по теме «{query}»" if query else "")
            + f", сделай по ним короткую сводку и сохрани её в файл «{fname}».")

    trace: list[dict] = []
    steering_calls = 0   # модель РЕШАЕТ «что звать дальше» — каждый ход цикла
    work_calls = 0       # модель ДЕЛАЕТ контент — вызов LLM внутри summarize
    steering_tokens = 0  # токены походов-за-решением (растут: вся история заново — боль Дня 8)
    work_tokens = 0      # токены самой сводки (работа)
    routing_decisions = 0
    last_summary = ""
    last_path = ""

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    llm = _client()

    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_list = (await session.list_tools()).tools
            read_only = {
                t.name: bool(getattr(t.annotations, "readOnlyHint", False)) if t.annotations else False
                for t in tool_list
            }
            openai_tools = _mcp_tools_to_openai(tool_list)
            trace.append({"kind": "offer", "tools": [t.name for t in tool_list], "task": task})

            for _step in range(6):  # потолок ходов — защита от зацикливания (бриф: всегда нужен)
                resp = _llm_with_retry(
                    llm, model=MODEL, messages=messages,
                    tools=openai_tools, tool_choice="auto",
                    max_tokens=1500, extra_body={"reasoning": {"effort": "low"}},
                )
                steering_calls += 1
                steering_tokens += int(getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0)
                msg = resp.choices[0].message

                # Модель решила НЕ звать инструмент — финальный ответ.
                if not msg.tool_calls:
                    trace.append({"kind": "final", "text": msg.content or ""})
                    break

                messages.append({
                    "role": "assistant", "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                })

                for tc in msg.tool_calls:
                    routing_decisions += 1
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    writes = not read_only.get(name, False)
                    confirmed = True
                    if writes and on_confirm is not None:
                        confirmed = bool(on_confirm(name, args))

                    if not confirmed:
                        result = {"ok": False, "error": "пользователь отклонил запись"}
                    else:
                        call = await session.call_tool(name, args)
                        result = _structured(call)
                        if name == "summarize":
                            work_calls += 1  # summarize внутри сходил к модели — это «работа»
                            work_tokens += int(result.get("tokens", 0) or 0)
                            if result.get("summary"):
                                last_summary = result["summary"]
                        if name == "save_to_file" and result.get("path"):
                            last_path = result["path"]

                    trace.append({
                        "kind": "tool", "step": name, "role": ROLE.get(name, name),
                        "input": _short_args(name, args), "ok": result.get("ok", False),
                        "output": result, "writes": writes, "confirmed": confirmed,
                        "by": "модель", "model_call_no": steering_calls,
                        "result_line": _result_line(name, result),
                    })

                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                trace.append({"kind": "final", "text": "(достигнут потолок ходов)"})

    saved = bool(last_path)
    return {
        "ok": saved, "mode": "agent", "trace": trace,
        # параллельно пайплайну: work = контент, steering = выбор порядка, llm = всего
        "work_calls": work_calls,
        "steering_calls": steering_calls,
        "llm_calls": steering_calls + work_calls,
        "routing_decisions": routing_decisions,
        # токены (честный серверный usage): работа ≈ как у пайплайна, руление — наценка агента
        "work_tokens": work_tokens,
        "steering_tokens": steering_tokens,
        "total_tokens": steering_tokens + work_tokens,
        "summary": last_summary, "file_path": last_path,
    }


def _short_args(name: str, args: dict) -> dict:
    """Не тащить в трассу гигантский массив постов — показать его одной строкой."""
    out = dict(args)
    if "posts" in out and isinstance(out["posts"], list):
        out["posts"] = f'[{len(out["posts"])} постов от шага search]'
    if "content" in out and isinstance(out["content"], str) and len(out["content"]) > 60:
        out["content"] = f'[сводка от шага summarize, {len(out["content"])} симв.]'
    return out


def _result_line(name: str, r: dict) -> str:
    if not r.get("ok"):
        return f'ошибка: {r.get("error", "—")}'
    if name == "search":
        return f'нашёл постов: {r.get("count", 0)}'
    if name == "summarize":
        return f'сводка готова ({len(r.get("summary", ""))} симв.)'
    if name == "save_to_file":
        return f'записано: {r.get("filename")} ({r.get("bytes", 0)} байт)'
    return "готово"


if __name__ == "__main__":
    import asyncio
    import sys
    sub = sys.argv[1] if len(sys.argv) > 1 else "LocalLLaMA"
    q = sys.argv[2] if len(sys.argv) > 2 else ""
    out = asyncio.run(run_agent(sub, q))
    print(json.dumps(out, ensure_ascii=False, indent=2))

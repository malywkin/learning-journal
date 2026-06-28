"""
День 20 — ХОСТ-АГЕНТ: держит по одному клиенту на КАЖДЫЙ из трёх серверов, склеивает все
их инструменты в ОДИН список и маршрутизирует вызовы на нужный сервер.

Это сердце дня. Три вещи «под капотом», ровно как в спеке MCP и в Claude Code:

1. ОДИН клиент на сервер. Хост открывает три отдельных соединения (reddit/storage/utils)
   и у каждого спрашивает tools/list.

2. ЕДИНЫЙ список с префиксом. Имена с разных серверов могут совпасть, а неймспейса в самом
   протоколе нет — разруливает хост. Префиксуем `server__tool` (точь-в-точь как Claude Code
   делает `mcp__server__tool`). Модель видит плоский список кнопок и НЕ знает, что их три
   сервера, — она выбирает по имени.

3. МАРШРУТИЗИРУЕТ хост, не модель. Модель сказала «зови storage__save_note» — хост сам
   отрезает префикс `storage__`, находит нужное соединение и шлёт вызов туда. Это и есть
   «корректно маршрутизировал запросы» из задания.

Длинный флоу через РАЗНЫЕ серверы (сценарий по умолчанию):
  reddit__search_reddit → reddit__summarize_posts → utils__translate_ru → utils__now
  → storage__save_note
Состояние между вызовами протокол не хранит (stateless): выход одного шага модель сама
переносит во вход следующего (посты → сводка → перевод → файл). Мы это показываем в трассе.
"""

import json
import os
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import llm

# Три сервера, каждый на своём порту. Имя слева = префикс неймспейса.
SERVERS = {
    "reddit": "http://127.0.0.1:8101/mcp",
    "storage": "http://127.0.0.1:8102/mcp",
    "utils": "http://127.0.0.1:8103/mcp",
}
SEP = "__"  # разделитель префикса: reddit__search_reddit

# Зависимости порядка: инструмент X нельзя звать раньше, чем отработал Y (его вход — выход Y).
ORDER_DEPS = {
    "summarize_posts": "search_reddit",
    "translate_ru": "summarize_posts",
    "save_note": "translate_ru",
}

SYSTEM = (
    "Ты ассистент с доступом к инструментам на НЕСКОЛЬКИХ серверах. Имена инструментов имеют "
    "вид server__tool (сервер до '__'). Тебе дают задачу — выполни её ЦЕПОЧКОЙ вызовов, по "
    "одному за раз, выбирая нужный инструмент с нужного сервера.\n"
    "Доступные инструменты:\n"
    "  • reddit__search_reddit(subreddit, query, limit) — найти посты;\n"
    "  • reddit__summarize_posts(posts, subreddit) — свернуть НАЙДЕННЫЕ посты в дайджест (англ.);\n"
    "  • utils__translate_ru(text) — перевести дайджест на русский;\n"
    "  • utils__now() — текущее время для отметки;\n"
    "  • storage__save_note(title, content) — сохранить итог в заметку.\n"
    "Порядок: сначала search; затем summarize по полю posts из его результата; затем "
    "translate_ru по полю summary; возьми время через now; в конце save_note, где content = "
    "русский перевод плюс строка с временем. Данные бери ТОЛЬКО из результатов инструментов, "
    "ничего не выдумывай. Когда заметка сохранена — кратко ответь по-русски, что сделано."
)


def _structured(call) -> dict:
    """Достать машиночитаемый результат: сперва structuredContent, иначе разобрать текст."""
    if call.structuredContent:
        sc = call.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    if call.content and getattr(call.content[0], "text", None):
        try:
            return json.loads(call.content[0].text)
        except json.JSONDecodeError:
            return {"text": call.content[0].text}
    return {}


def _short_args(args: dict) -> dict:
    """Не тащить в трассу тяжёлое: список постов и длинный текст — одной строкой."""
    out = dict(args)
    if isinstance(out.get("posts"), list):
        out["posts"] = f'[{len(out["posts"])} постов от reddit__search_reddit]'
    for k in ("content", "text"):
        v = out.get(k)
        if isinstance(v, str) and len(v) > 60:
            out[k] = f"[{len(v)} симв. от предыдущего шага]"
    return out


def _result_line(tool: str, r: dict) -> str:
    if not r.get("ok"):
        return f'ошибка: {r.get("error", "—")}'
    if tool == "search_reddit":
        return f'нашёл постов: {r.get("count", 0)}'
    if tool == "summarize_posts":
        return f'дайджест готов ({len(r.get("summary", ""))} симв., англ.)'
    if tool == "translate_ru":
        return f'переведено на русский ({len(r.get("text_ru", ""))} симв.)'
    if tool == "now":
        return f'время: {r.get("human", "")} — {r.get("source", "")}'
    if tool == "save_note":
        return f'сохранено: {r.get("filename")} ({r.get("bytes", 0)} байт)'
    return "готово"


def _check_order(sequence: list[str]) -> list[dict]:
    """Проверка из задания — «корректность порядка». Для каждого вызова смотрим: отработал ли
    уже инструмент, от которого он зависит? Если нет — нарушение (сохранил раньше, чем перевёл)."""
    seen: set[str] = set()
    violations = []
    for tool in sequence:
        dep = ORDER_DEPS.get(tool)
        if dep and dep not in seen:
            violations.append({"tool": tool, "needs": dep})
        seen.add(tool)
    return violations


async def run_flow(subreddit: str, query: str = "") -> dict:
    """Дать хост-агенту задачу и дать ему самому пройти цепочку через три сервера.
    Возвращает трассу для витрины: какой сервер → какой инструмент, в каком порядке."""
    task = (f"Сделай дайджест свежих постов из r/{subreddit}"
            + (f" по теме «{query}»" if query else "")
            + ", переведи его на русский, проставь текущее время и сохрани заметкой "
            + f"под названием «{subreddit}_digest».")

    trace: list[dict] = []
    sequence: list[str] = []          # порядок базовых имён инструментов — для проверки
    routes: list[dict] = []           # куда хост направил каждый вызов
    steering_calls = 0                # сколько раз дёрнули модель за решением «что дальше»
    last = {"note": "", "path": ""}

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]

    async with AsyncExitStack() as stack:
        # 1) поднять по клиенту на каждый сервер и собрать их инструменты
        sessions: dict[str, ClientSession] = {}
        registry: dict[str, tuple[str, str]] = {}   # prefixed -> (server, original)
        offer = []                                   # для витрины: какой сервер что предложил
        openai_tools = []

        for server, url in SERVERS.items():
            read, write, _ = await stack.enter_async_context(streamablehttp_client(url))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[server] = session
            tools = (await session.list_tools()).tools
            names = []
            for t in tools:
                prefixed = f"{server}{SEP}{t.name}"     # неймспейс: server__tool
                registry[prefixed] = (server, t.name)
                names.append(t.name)
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": prefixed,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    },
                })
            offer.append({"server": server, "tools": names})

        trace.append({"kind": "offer", "task": task, "servers": offer,
                      "merged": [t["function"]["name"] for t in openai_tools]})

        # 2) цикл агента: модель сама выбирает инструмент, хост маршрутизирует на нужный сервер
        for _step in range(8):  # потолок ходов — защита от зацикливания
            resp = llm.chat_with_retry(
                model=llm.MODEL, messages=messages, tools=openai_tools,
                tool_choice="auto", max_tokens=1500, extra_body={"reasoning": {"effort": "low"}},
            )
            steering_calls += 1
            msg = resp.choices[0].message

            if not msg.tool_calls:  # модель решила больше не звать инструменты — это финал
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
                prefixed = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                # МАРШРУТИЗАЦИЯ: отрезаем префикс, находим нужный сервер
                if prefixed in registry:
                    server, tool = registry[prefixed]
                else:  # модель назвала имя без/с неверным префиксом — пытаемся разобрать
                    server, _, tool = prefixed.partition(SEP)
                    if server not in sessions:
                        server, tool = "?", prefixed

                routes.append({"chose": prefixed, "routed_to": server})

                if server in sessions and tool:
                    call = await sessions[server].call_tool(tool, args)
                    result = _structured(call)
                else:
                    result = {"ok": False, "error": f"нет такого инструмента: {prefixed}"}

                sequence.append(tool)
                if tool == "translate_ru" and result.get("text_ru"):
                    last["note"] = result["text_ru"]
                if tool == "save_note" and result.get("path"):
                    last["path"] = result["path"]

                trace.append({
                    "kind": "tool", "server": server, "tool": tool, "chose": prefixed,
                    "input": _short_args(args), "ok": result.get("ok", False),
                    "writes": (tool == "save_note"),
                    "result_line": _result_line(tool, result),
                    "step_no": len(sequence),
                })

                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        else:
            trace.append({"kind": "final", "text": "(достигнут потолок ходов)"})

    violations = _check_order(sequence)
    servers_used = sorted({r["routed_to"] for r in routes if r["routed_to"] in SERVERS})
    return {
        "ok": bool(last["path"]) and not violations,
        "trace": trace,
        "routes": routes,
        "sequence": sequence,
        "servers_used": servers_used,
        "cross_server": len(servers_used) >= 2,   # инструменты с РАЗНЫХ серверов — пункт задания
        "order_ok": not violations,
        "violations": violations,
        "steering_calls": steering_calls,
        "note_ru": last["note"],
        "file_path": last["path"],
    }


if __name__ == "__main__":
    import asyncio
    import sys
    sub = sys.argv[1] if len(sys.argv) > 1 else "LocalLLaMA"
    q = sys.argv[2] if len(sys.argv) > 2 else ""
    out = asyncio.run(run_flow(sub, q))
    print(json.dumps(out, ensure_ascii=False, indent=2))

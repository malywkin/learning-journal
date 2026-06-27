"""
День 17 — агент, который ПОЛЬЗУЕТСЯ нашим MCP-сервером.

Это вторая половина задания: «подключите инструмент к агенту, вызовите из приложения,
получите и используйте результат». Агент совмещает две роли:
  • MCP-КЛИЕНТ — подключается к нашему серверу, берёт список инструментов (tools/list),
    при необходимости шлёт вызов (tools/call);
  • обвязку вокруг LLM (OpenRouter) — отдаёт модели меню инструментов и крутит цикл:
    модель сама решает позвать инструмент → мы выполняем вызов → результат возвращаем
    модели → она отвечает уже с данными.

Что под капотом стоит запомнить:
  • выбор инструмента делает САМА модель (tool_choice="auto") — в этом суть агента;
  • на инструмент, который ПИШЕТ (readOnlyHint=False), ставим человека-в-цикле:
    спрашиваем подтверждение до вызова (рекомендация по безопасности MCP 2026);
  • слабая модель (gpt-oss-20b) на "auto" инструмент звать отказывается — берём 120b.
"""

import json
import os
import time

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

SERVER_URL = "http://127.0.0.1:8017/mcp"
MODEL = "openai/gpt-oss-120b:free"   # 20b на "auto" не зовёт инструмент — проверено живьём

SYSTEM = (
    "Ты ассистент CRM-системы. У тебя есть инструменты для работы с базой клиентов. "
    "Данные о клиентах ты не знаешь наизусть — всегда получай их через инструменты, "
    "не выдумывай. Если просят найти/показать клиентов — вызови поиск. Если просят "
    "завести/добавить клиента — вызови создание. После вызова кратко ответь по-русски, "
    "опираясь на полученные данные."
)


def _client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=90,  # без таймаута зависший free-провайдер вешает весь запрос
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


def mcp_tools_to_openai(tools) -> list[dict]:
    """Переводим описания инструментов MCP в формат, который понимает LLM-API."""
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


class CrmAgent:
    """Агент поверх MCP-сервера CRM. on_confirm(name, args)->bool — человек-в-цикле."""

    def __init__(self, server_url: str = SERVER_URL, model: str = MODEL, on_confirm=None):
        self.server_url = server_url
        self.model = model
        self.on_confirm = on_confirm
        self.llm = _client()

    async def ask(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Один заход агента. Возвращает финальный ответ + трассу шагов для витрины."""
        trace: list[dict] = []
        messages = [{"role": "system", "content": SYSTEM}]
        if history:
            messages += history
        messages.append({"role": "user", "content": user_message})

        # Открываем соединение с НАШИМ MCP-сервером на время всего захода.
        async with streamablehttp_client(self.server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tool_list = (await session.list_tools()).tools
                # какие инструменты только читают — нужно для человека-в-цикле
                read_only = {
                    t.name: bool(getattr(t.annotations, "readOnlyHint", False)) if t.annotations else False
                    for t in tool_list
                }
                openai_tools = mcp_tools_to_openai(tool_list)
                trace.append({"type": "tools_offered", "tools": [t.name for t in tool_list]})

                for _step in range(5):  # потолок шагов — защита от зацикливания
                    resp = _llm_with_retry(
                        self.llm,
                        model=self.model,
                        messages=messages,
                        tools=openai_tools,
                        tool_choice="auto",
                        max_tokens=1200,
                        extra_body={"reasoning": {"effort": "low"}},
                    )
                    msg = resp.choices[0].message

                    # Модель решила НЕ звать инструмент — это финальный ответ.
                    if not msg.tool_calls:
                        trace.append({"type": "final", "text": msg.content or ""})
                        return {"answer": msg.content or "", "trace": trace}

                    # Сохраняем ход ассистента с его tool_calls (нужно для протокола).
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                            }
                            for tc in msg.tool_calls
                        ],
                    })

                    # Выполняем каждый запрошенный вызов.
                    for tc in msg.tool_calls:
                        name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}

                        writes = not read_only.get(name, False)
                        confirmed = True
                        if writes and self.on_confirm is not None:
                            confirmed = bool(self.on_confirm(name, args))

                        if not confirmed:
                            result_text = "Пользователь отклонил этот вызов — запись не выполнена."
                            trace.append({
                                "type": "tool_call", "name": name, "args": args,
                                "writes": writes, "confirmed": False, "result": None,
                            })
                        else:
                            call = await session.call_tool(name, args)
                            result_text = call.content[0].text if call.content else ""
                            trace.append({
                                "type": "tool_call", "name": name, "args": args,
                                "writes": writes, "confirmed": True,
                                "result_text": result_text,
                                "result_structured": call.structuredContent,
                            })

                        # Возвращаем результат вызова обратно модели.
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_text,
                        })

                # Если упёрлись в потолок шагов — отдаём, что есть.
                trace.append({"type": "final", "text": "(достигнут потолок шагов)"})
                return {"answer": "(достигнут потолок шагов)", "trace": trace}

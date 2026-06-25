"""
День 16 — подключение к готовому MCP-серверу и вывод списка его инструментов.

Этот скрипт — MCP-КЛИЕНТ (наш «дозвонщик»). Он:
  1) подключается к чужому, уже работающему MCP-серверу по сети (транспорт Streamable HTTP);
  2) делает рукопожатие (initialize) — без него сервер не начнёт отвечать;
  3) просит у сервера список инструментов (tools/list) и печатает его.

Свой сервер мы НЕ пишем — дёргаем существующий (DeepWiki), он открыт без авторизации.
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Готовые публичные MCP-серверы без авторизации. Берём первый, который ответит
# (второй — на случай, если первый недоступен в момент записи видео).
SERVERS = [
    ("DeepWiki", "https://mcp.deepwiki.com/mcp"),
    ("Microsoft Learn", "https://learn.microsoft.com/api/mcp"),
]


async def show_tools(name: str, url: str) -> None:
    print(f"\nПодключаюсь к серверу «{name}»: {url}")

    # streamablehttp_client открывает соединение и даёт два канала — чтение и запись;
    # третий элемент (id сессии) нам не нужен, прячем в _.
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()            # рукопожатие MCP
            info = init.serverInfo
            print(f"  Соединение установлено. Сервер: {info.name} {info.version}")

            result = await session.list_tools()          # сам запрос tools/list
            tools = result.tools
            print(f"  Инструментов получено: {len(tools)}\n")

            for i, tool in enumerate(tools, 1):
                print(f"  {i}. {tool.name}")
                if tool.description:
                    # первая строка описания, чтобы вывод не разрастался
                    print(f"     {tool.description.strip().splitlines()[0]}")

                schema = tool.inputSchema or {}
                props = schema.get("properties", {})
                required = set(schema.get("required", []))
                if props:
                    params = ", ".join(
                        f"{p}{'*' if p in required else ''}" for p in props
                    )
                    print(f"     параметры: {params}   (* — обязательный)")
                print()


async def main() -> None:
    for name, url in SERVERS:
        try:
            await show_tools(name, url)
            return                       # хватит первого успешного сервера
        except Exception as e:
            print(f"  Не вышло ({type(e).__name__}: {e}). Пробую следующий...")
    print("\nНи один сервер не ответил.")


if __name__ == "__main__":
    asyncio.run(main())

"""
День 17 — НАШ MCP-сервер вокруг локальной CRM (crm.py).

Здесь — все три пункта задания:
  • регистрация инструмента        — декоратор @mcp.tool на обычной функции;
  • описание входных параметров    — схема рождается из подсказок типов + Field(...);
  • возврат результата             — возвращаем dict, FastMCP сам отдаёт его и текстом,
                                      и машиночитаемой структурой (structuredContent).

Транспорт — Streamable HTTP (тот же, по которому на Дне 16 мы как КЛИЕНТ ходили к
DeepWiki). Слушаем только 127.0.0.1 — спецификация требует не выставлять MCP-сервер
наружу (защита от DNS-rebinding). Запуск:  python mcp_server.py
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import crm

# Готовим предметную базу (создаём таблицу + демо-клиентов при первом запуске).
crm.init_db()

# Имя сервера видит клиент при рукопожатии. host=127.0.0.1 — только локально.
mcp = FastMCP("crm-day17", host="127.0.0.1", port=8017)


# Описываем ФОРМУ результата (structured output, фишка спецификации 2025-06-18).
# Когда инструмент возвращает Pydantic-модель, FastMCP кладёт в ответ не только текст,
# но и outputSchema + машиночитаемый structuredContent — клиенту не нужно парсить строку.
class Client(BaseModel):
    id: int
    name: str
    email: Optional[str] = ""
    status: str
    note: Optional[str] = ""
    created_at: str


class SearchResult(BaseModel):
    count: int
    clients: list[Client]


class CreateResult(BaseModel):
    created: Client


@mcp.tool(
    annotations=ToolAnnotations(
        title="Поиск клиентов",
        readOnlyHint=True,    # инструмент ТОЛЬКО читает — клиент может звать без спроса
        openWorldHint=False,  # данные локальные, в интернет не ходим
    )
)
def search_clients(
    query: Annotated[str, Field(description="строка поиска по имени, почте или заметке; пусто = вернуть всех")] = "",
    status: Annotated[Optional[Literal["lead", "active", "churned"]], Field(description="фильтр по стадии воронки")] = None,
    limit: Annotated[int, Field(description="сколько записей вернуть максимум", ge=1, le=50)] = 5,
) -> SearchResult:
    """Найти клиентов в CRM по подстроке и/или стадии. Только читает, ничего не меняет."""
    found = crm.search_clients(query=query, status=status, limit=limit)
    return SearchResult(count=len(found), clients=[Client(**r) for r in found])


@mcp.tool(
    annotations=ToolAnnotations(
        title="Создать клиента",
        readOnlyHint=False,     # инструмент ПИШЕТ — повод спросить человека перед вызовом
        destructiveHint=False,  # не разрушает существующее, только добавляет
        idempotentHint=False,   # повтор создаст дубль — не идемпотентен
        openWorldHint=False,
    )
)
def create_client(
    name: Annotated[str, Field(description="имя клиента — обязательное поле")],
    email: Annotated[str, Field(description="электронная почта (необязательно)")] = "",
    status: Annotated[Literal["lead", "active", "churned"], Field(description="стадия воронки")] = "lead",
    note: Annotated[str, Field(description="короткая заметка по клиенту")] = "",
) -> CreateResult:
    """Завести нового клиента в CRM. ВНИМАНИЕ: изменяет данные — создаёт запись."""
    created = crm.create_client(name=name, email=email, status=status, note=note)
    return CreateResult(created=Client(**created))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

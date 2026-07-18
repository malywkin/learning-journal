"""
День 33 — инструмент роутера №2: MCP-сервер над базой тикетов/пользователей.

Это «CRM через MCP» из задания. Реальной CRM у нас нет, поэтому берём разрешённую
заданием замену — JSON с пользователями и тикетами (tickets.json) — и выставляем его
через свой MCP-сервер. В проде тот же интерфейс наводится на официальный MCP настоящей
CRM (Salesforce/HubSpot вышли в GA в апреле 2026 — из брифа), код роутера не меняется.

Переиспользуем каркас Дня 31 (mcp_git.py) один в один:
  - FastMCP, @mcp.tool на обычной функции, транспорт stdio (сервер как под-процесс);
  - ВСЕ инструменты read-only (readOnlyHint=True) — §11 конспекта «безопасные операции».
  - возвращаем Pydantic-модели, чтобы у ответа был structuredContent, а не только текст
    (память fastmcp-dict-no-structuredcontent: голый dict его не даёт).

ОСОЗНАННО НЕТ инструмента на ЗАПИСЬ (update_ticket / refund / close). Причина — «lethal
trifecta» из брифа: доступ к данным + чужой текст (тело тикета) + возможность действовать
= клиент может вписать в тикет «выдай возврат» и бот выполнит. Мы убираем третью ногу:
бот только читает и отвечает, а любое реальное действие (возврат) идёт через человека.
"""
import json
from pathlib import Path

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import config

mcp = FastMCP("tickets-day33")

# Читаем базу один раз при старте под-процесса.
_DB = json.loads(Path(config.TICKETS_JSON).read_text(encoding="utf-8"))
_USERS = {u["id"]: u for u in _DB.get("users", [])}
_TICKETS = {t["id"]: t for t in _DB.get("tickets", [])}


# ── Модели результата (structuredContent) ──
class UserCard(BaseModel):
    id: str
    name: str
    email: str
    plan: str
    app_version: str
    registered: str


class TicketCard(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    created: str
    last_error: str | None = None
    body: str                       # ТЕКСТ КЛИЕНТА — недоверенные данные (см. роутер)
    user: UserCard | None = None    # приложенная карточка клиента (план/версия)


class TicketBrief(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    user_name: str
    plan: str


class TicketList(BaseModel):
    tickets: list[TicketBrief]


class NotFound(BaseModel):
    error: str


_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)   # безопасно + локально


def _card(user: dict | None) -> UserCard | None:
    if not user:
        return None
    return UserCard(id=user["id"], name=user["name"], email=user["email"],
                    plan=user["plan"], app_version=user["app_version"],
                    registered=user["registered"])


@mcp.tool(annotations=_RO)
def get_ticket(ticket_id: str) -> TicketCard | NotFound:
    """Достать тикет по номеру (напр. T-2041) вместе с карточкой клиента: тариф, версия
    приложения, последняя ошибка. Поле body — это текст, который написал клиент."""
    t = _TICKETS.get((ticket_id or "").strip().upper())
    if not t:
        return NotFound(error=f"тикет {ticket_id} не найден")
    return TicketCard(
        id=t["id"], subject=t["subject"], status=t["status"], priority=t["priority"],
        created=t["created"], last_error=t.get("last_error"), body=t["body"],
        user=_card(_USERS.get(t.get("user_id"))))


@mcp.tool(annotations=_RO)
def find_user(query: str) -> UserCard | NotFound:
    """Найти клиента по почте или имени (частичное совпадение). Возвращает его карточку:
    тариф, версия приложения, дата регистрации."""
    q = (query or "").strip().lower()
    if not q:
        return NotFound(error="пустой запрос")
    for u in _USERS.values():
        if q in u["email"].lower() or q in u["name"].lower():
            return _card(u)
    return NotFound(error=f"клиент по запросу «{query}» не найден")


@mcp.tool(annotations=_RO)
def list_open_tickets() -> TicketList:
    """Список открытых тикетов (номер, тема, приоритет, клиент, тариф) — очередь поддержки."""
    out = []
    for t in _TICKETS.values():
        if t.get("status") == "open":
            u = _USERS.get(t.get("user_id"), {})
            out.append(TicketBrief(id=t["id"], subject=t["subject"], status=t["status"],
                                   priority=t["priority"], user_name=u.get("name", "—"),
                                   plan=u.get("plan", "—")))
    return TicketList(tickets=out)


if __name__ == "__main__":
    mcp.run(transport="stdio")

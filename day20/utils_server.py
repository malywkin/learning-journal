"""
День 20 — СЕРВЕР №3 «utils». Третья стойка. Мелкие утилиты.

Что умеет:
  • now()             — текущее время. Учебный двойник официального сервера `time`.
  • translate_ru(text) — перевести текст на русский (через OpenRouter).

Главный показательный инструмент дня — now(). Это ответ на тот контрольный вопрос:
«сервер с now — КУДА подключается?» Никуда. Он смотрит на часы операционной системы
(datetime прямо в процессе) и отдаёт время. Ни интернета, ни диска. Сервер вовсе НЕ обязан
куда-то ходить — вот живой пример.

(А translate_ru на той же стойке как раз наружу ходит — к OpenRouter. То есть «подключается
или нет» — свойство КОНКРЕТНОГО инструмента, а не сервера целиком.)

Слушает 127.0.0.1:8103, Streamable HTTP.
"""

from datetime import datetime

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import llm


class NowResult(BaseModel):
    ok: bool
    iso: str = ""
    human: str = ""
    source: str = ""  # нарочно показываем, ОТКУДА взято время


class TranslateResult(BaseModel):
    ok: bool
    text_ru: str = ""
    tokens: int = 0
    error: str = ""


mcp = FastMCP("utils", host="127.0.0.1", port=8103)


@mcp.tool(annotations=ToolAnnotations(title="Текущее время", readOnlyHint=True))
def now() -> NowResult:
    """Вернуть текущую дату и время. НИКУДА не подключается — читает часы операционной
    системы. Нужен во флоу, чтобы проставить в заметке отметку «когда сделано»."""
    t = datetime.now()
    return NowResult(
        ok=True,
        iso=t.isoformat(timespec="seconds"),
        human=t.strftime("%d.%m.%Y %H:%M"),
        source="часы ОС (никаких сетевых вызовов)",
    )


@mcp.tool(annotations=ToolAnnotations(title="Перевод на русский (LLM)", readOnlyHint=True))
def translate_ru(text: str) -> TranslateResult:
    """Перевести текст на русский. Берёт на вход английскую сводку (выход summarize_posts)
    и отдаёт русский вариант — его потом сохранит storage. Под капотом зовёт OpenRouter."""
    if not text or not text.strip():
        return TranslateResult(ok=False, error="пустой вход: нечего переводить")
    messages = [
        {"role": "system", "content": (
            "Ты переводчик. Переведи текст пользователя на русский язык точно и естественно. "
            "Сохрани разметку и пункты списка. Не добавляй и не убирай факты. Выведи ТОЛЬКО перевод."
        )},
        {"role": "user", "content": text},
    ]
    try:
        resp = llm.chat_with_retry(
            model=llm.MODEL, messages=messages, temperature=0, max_tokens=600,
            extra_body={"reasoning": {"effort": "low"}},
        )
    except Exception as e:
        return TranslateResult(ok=False, error=f"LLM: {type(e).__name__}")
    text_ru = (resp.choices[0].message.content or "").strip()
    tokens = int(getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0)
    return TranslateResult(ok=True, text_ru=text_ru, tokens=tokens)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

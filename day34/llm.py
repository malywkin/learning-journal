"""
День 34 — провайдер модели: DeepSeek основной, локальный qwen3.5 (LM Studio) запасной.

Переиспользован с Дня 31 без изменений. Это §14 конспекта (Retry → Fallback →
Human-in-the-Loop) в миниатюре: сначала основная модель; упала (сеть/500) — падаем
на локальную. Обе — по одному OpenAI-совместимому SDK (развязка провайдера Дня 24:
меняется только base_url + ключ + имя модели). Ключ читаем из .env, не хардкодим.
"""
import os
from pathlib import Path

from openai import AsyncOpenAI

import config

# ---------- .env (ключи не в коде) ----------
_ENV = Path(__file__).resolve().parent / ".env"
for _line in _ENV.read_text().splitlines() if _ENV.exists() else []:
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())


def _providers() -> list[dict]:
    """Порядок попыток: DeepSeek (если есть ключ) → локальный LM Studio."""
    out = []
    if os.getenv("DEEPSEEK_API_KEY"):
        out.append({"name": "deepseek", "base_url": config.DEEPSEEK_BASE_URL,
                    "api_key": os.environ["DEEPSEEK_API_KEY"], "model": config.DEEPSEEK_MODEL})
    out.append({"name": "local", "base_url": config.LOCAL_BASE_URL,
                "api_key": "lm-studio", "model": config.LOCAL_MODEL})
    return out


_clients: dict[str, AsyncOpenAI] = {}


def _client(p: dict) -> AsyncOpenAI:
    if p["name"] not in _clients:
        _clients[p["name"]] = AsyncOpenAI(base_url=p["base_url"], api_key=p["api_key"], timeout=90)
    return _clients[p["name"]]


async def chat(messages: list[dict], tools: list[dict] | None = None):
    """Один ход разговора. Возвращает (message, имя_провайдера).

    tools=None → просим ТЕКСТОВЫЙ ответ без вызовов (финальная синтез-реплика, когда
    исчерпали круги инструментов). Fallback §14: основной упал — пробуем следующий;
    все упали — честная ошибка текстом (не роняем приложение)."""
    last_err = "нет провайдеров"
    kw = {"tools": tools, "tool_choice": "auto"} if tools else {}
    for p in _providers():
        try:
            r = await _client(p).chat.completions.create(
                model=p["model"], messages=messages,
                temperature=0, max_tokens=1600, **kw)
            return r.choices[0].message, p["name"]
        except Exception as e:
            last_err = f"{p['name']}: {type(e).__name__}"
            continue

    class _Stub:
        content = f"(модель недоступна: {last_err})"
        tool_calls = None
    return _Stub(), "none"

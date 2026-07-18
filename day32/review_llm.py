"""
День 32 — мотор запроса к модели для ревью. Переиспой Дня 31 (провайдер-развязка),
но цепочка облачная: DeepSeek → OpenRouter.

Здесь живёт §14 конспекта в коде:
  • Retry — до MAX_RETRIES попыток на каждого провайдера (сеть/мусор/пустой ответ).
  • Fallback — основной провайдер сдох → идём к следующему по цепочке.
  • Никогда не роняем job — если всё упало, возвращаем None, а не исключение наружу.

Структурный ответ берём мягким json_object + шаблон в промпте + разбор кодом —
строгий json_schema не держат провайдеры (наша грабля Дня 24, память
structured-output-json-object-not-schema).
"""
import json
import os
import time
from pathlib import Path

from openai import OpenAI

import config

# ── .env (ключи не в коде): локально читаем, в CI ключ приходит из секрета ──
_ENV = Path(__file__).resolve().parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


def _providers() -> list[dict]:
    """Цепочка попыток: DeepSeek (если есть ключ) → OpenRouter (если есть ключ)."""
    out = []
    if os.getenv("DEEPSEEK_API_KEY"):
        out.append({"name": "deepseek", "base_url": config.DEEPSEEK_BASE_URL,
                    "key": os.environ["DEEPSEEK_API_KEY"], "model": config.DEEPSEEK_MODEL})
    if os.getenv("OPENROUTER_API_KEY"):
        out.append({"name": "openrouter", "base_url": config.OPENROUTER_BASE_URL,
                    "key": os.environ["OPENROUTER_API_KEY"], "model": config.OPENROUTER_MODEL})
    return out


def ask_json(system: str, user: str) -> tuple[dict | None, str]:
    """Вернуть (разобранный_json, имя_провайдера).

    Retry → Fallback (§14): каждого провайдера пробуем до MAX_RETRIES раз; если
    вернул невалидный/пустой json — считаем это сбоем и пробуем снова/дальше.
    Всё упало → (None, "none"): пусть вызывающий решит (не постить, не ронять job).
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    providers = _providers()
    if not providers:
        return None, "none"

    for p in providers:
        client = OpenAI(base_url=p["base_url"], api_key=p["key"], timeout=90)
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                r = client.chat.completions.create(
                    model=p["model"], messages=messages,
                    temperature=0, max_tokens=1500,
                    response_format={"type": "json_object"})
                raw = (r.choices[0].message.content or "").strip()
                data = json.loads(raw)                 # мусор/не json → в except → retry
                if isinstance(data, dict) and data:
                    return data, p["name"]
            except Exception as e:
                # прогрессивная пауза между попытками (§14): 0с, 2с, 4с
                print(f"[llm] {p['name']} попытка {attempt}/{config.MAX_RETRIES} "
                      f"не удалась: {type(e).__name__}", flush=True)
                time.sleep(2 * attempt)
                continue
    return None, "none"

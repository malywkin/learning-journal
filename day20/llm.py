"""
День 20 — общий доступ к LLM (OpenRouter), которым пользуются ДВА разных сервера:
reddit-сервер (сводка постов) и utils-сервер (перевод на русский).

Вынесено в отдельный модуль нарочно: так видно, что «сходить к модели» — это ВНУТРЕННЕЕ
дело сервера, а не часть MCP. Снаружи (для агента) и summarize_posts, и translate_ru —
просто инструменты; то, что под капотом они зовут OpenRouter, агент не видит и знать не
обязан. Ровно та мысль, что мы снимали на фундаменте: связь «агент ↔ сервер» — это MCP,
а связь «сервер → OpenRouter» — личная кухня сервера.

Бесплатные модели OpenRouter любят отдавать 429 (rate-limit) и иногда висят — поэтому
короткие ретраи с backoff и обязательный timeout (память: free-tier reality).
"""

import os
import time

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

load_dotenv()

MODEL = "openai/gpt-oss-120b:free"  # 120b ровнее держит формат и зовёт инструменты, чем 20b
_RETRY_429 = 4


def client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=90,  # без таймаута зависший free-провайдер вешает весь запрос
    )


def chat_with_retry(**kwargs):
    """Вызов модели с короткими ретраями на 429 (free-tier любит rate-limit)."""
    delay = 2
    for attempt in range(_RETRY_429):
        try:
            return client().chat.completions.create(**kwargs)
        except APIStatusError as e:
            if e.status_code == 429 and attempt < _RETRY_429 - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise

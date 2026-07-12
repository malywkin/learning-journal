"""День 27 — адаптер: наш RAG-конвейер (дни 21–24) → ЛОКАЛЬНАЯ модель в LM Studio.

Мост к пройденному: весь ум конвейера уже собран в grounded.py (день 24):
поиск (день 21) → реранк (день 23) → порог-отказ → контракт {answer,sources,quotes}
→ проверка цитат кодом → судья. Мы НЕ трогаем этот ум. Меняем ровно одно —
МОТОР генерации: облако OpenRouter → http://127.0.0.1:1234 (LM Studio).

Единственная возня — reasoning. Модель qwen3.5-9b (MLX-сборка) залипает во внутреннем
монологе: 73 с на ответ. Флаги гашения (enable_thinking, reasoning.effort, /no_think)
на MLX-шаблоне мертвы — в шаблоне нет ветки, за которую они цепляются (баг-трекеры
LM Studio #1990/#2057). Обходим ТЕКСТОМ: подсовываем модели уже закрытый пустой
блок <think></think> как её же реплику — она видит «размышление закрыто» и сразу
пишет ответ. Замерено: 73 с → 3 с, ответ верный.
"""
import sys
import time
from pathlib import Path

from openai import OpenAI

BASE = Path(__file__).parent
for d in ("day22", "day23", "day24"):
    sys.path.insert(0, str(BASE.parent / d))
import grounded as gr  # noqa: E402  весь конвейер дня 24

LOCAL_BASE = "http://127.0.0.1:1234/v1"
LOCAL_MODEL = "qwen3.5-9b-mlx"
NOTHINK = {"role": "assistant", "content": "<think></think>"}  # гасим reasoning префиллом

_client = OpenAI(base_url=LOCAL_BASE, api_key="lm-studio", timeout=120)


def _chat_local(messages, json_mode=True, max_tokens=800, tries=3) -> str:
    """Замена gr._chat: тот же контракт вызова, но мотор локальный + гашение thinking.

    response_format НЕ ставим: LM Studio отвергает json_object (нужен json_schema),
    а наш толерантный gr._parse_json и так вытаскивает {..} из текста — контракт
    держит шаблон промпта (CONTRACT_TEMPLATE), а не строгий формат.
    """
    msgs = list(messages) + [NOTHINK]
    last = ""
    for _ in range(tries):
        try:
            r = _client.chat.completions.create(
                model=LOCAL_MODEL, temperature=0, max_tokens=max_tokens, messages=msgs)
            content = (r.choices[0].message.content or "").strip()
            if content:
                return content
            last = "(пустой ответ)"
        except Exception as e:
            last = f"({type(e).__name__})"
        time.sleep(2)
    return last


# Исходный (облачный) мотор конвейера — grounded при импорте выбрал DeepSeek
# (ключ в day24/.env). Запоминаем, чтобы кнопкой в боте возвращаться к нему.
_CLOUD = {"chat": gr._chat, "provider": gr.PROVIDER, "model": gr.MODEL}


def activate_local() -> None:
    """Мотор → локальная qwen (офлайн, гашение thinking префиллом)."""
    gr.PROVIDER = "local"
    gr.MODEL = LOCAL_MODEL
    gr._chat = _chat_local


def activate_cloud() -> None:
    """Мотор → облако DeepSeek (тот же конвейер, генерация в облаке)."""
    gr._chat = _CLOUD["chat"]
    gr.PROVIDER = _CLOUD["provider"]
    gr.MODEL = _CLOUD["model"]


activate = activate_local  # обратная совместимость со старым вызовом

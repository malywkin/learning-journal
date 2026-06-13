"""День 8 — счёт токенов и «как если бы» денег вокруг агента.

Три идеи дня (см. бриф):
  • ТОЧНЫЙ счёт даёт СЕРВЕР — в ответе приходит поле `usage`. Мы его только разбираем.
  • ЛОКАЛЬНО мы умеем лишь ПРИКИНУТЬ (до отправки), чтобы заранее увидеть «влезу/не влезу».
    Прикидка привязана к токенайзеру конкретной модели и всё равно слегка разойдётся
    с сервером (служебная разметка ролей + скрытые reasoning-токены сервер считает, мы — нет).
  • ДЕНЬГИ: модель бесплатная (в usage cost=0), поэтому показываем цену «как если бы»
    по примерному тарифу — тот же приём, что в Дне 5.
"""
import tiktoken

# gpt-oss режется токенайзером o200k_harmony (OpenAI, авг-2025). Если вдруг
# недоступен в установленной версии tiktoken — мягко откатываемся, чтобы
# прикидка продолжала работать (с небольшой потерей точности).
try:
    _ENC = tiktoken.get_encoding("o200k_harmony")
    ENC_NAME = "o200k_harmony"
except Exception:
    _ENC = tiktoken.get_encoding("o200k_base")
    ENC_NAME = "o200k_base"

# «Как если бы» тариф, USD за 1 млн токенов. ИЛЛЮСТРАТИВНЫЙ: у каждой платной
# модели свои цены (openrouter.ai/models). Вход почти всегда дешевле выхода.
PRICE_IN = 0.10    # $/1M входных токенов
PRICE_OUT = 0.40   # $/1M выходных токенов

# Контекстные окна наших моделей (число проверено живьём — см. текст ошибки 400).
CONTEXT_WINDOW = {
    "openai/gpt-oss-20b:free": 131072,
    "openai/gpt-oss-120b:free": 131072,
    "google/gemma-3-27b-it:free": 131072,
}
DEFAULT_WINDOW = 131072


def window_for(model):
    return CONTEXT_WINDOW.get(model, DEFAULT_WINDOW)


def estimate_text(text):
    """Прикидка: сколько токенов в куске текста (токенайзер o200k_harmony)."""
    return len(_ENC.encode(text or ""))


def estimate_messages(messages):
    """Прикидка токенов ВСЕГО, что уйдёт в модель (роли + содержимое).

    Это ОЦЕНКА: добавляем небольшой служебный overhead на каждое сообщение
    (обёртка роли) и «затравку» на ответ — как в кукбуке OpenAI. Точное число
    всё равно вернёт сервер в usage; расхождение в пару процентов — норма.
    """
    total = 0
    for m in messages:
        total += 3                       # обёртка роли: <|start|>role<|message|> … <|end|>
        total += estimate_text(m.get("content", ""))
    total += 3                           # «затравка» под ответ ассистента
    return total


def as_if_cost(prompt_tokens, completion_tokens):
    """Цена запроса «как если бы» по примерному тарифу (модель бесплатная)."""
    p = (prompt_tokens or 0) / 1_000_000 * PRICE_IN
    c = (completion_tokens or 0) / 1_000_000 * PRICE_OUT
    return p + c


def normalize_usage(usage):
    """Серверное поле usage → простой словарь. Берём, что реально пришло.

    ВАЖНО: reasoning_tokens (скрытые «мысли») и cached_tokens (кэш) лежат во
    вложенных деталях; на разных провайдерах они могут не «вкладываться» друг в
    друга чисто (живой зонд показал reasoning > completion), поэтому НЕ выводим
    одно из другого арифметикой — показываем как есть.
    """
    if usage is None:
        return None
    d = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    ctd = d.get("completion_tokens_details") or {}
    ptd = d.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": d.get("prompt_tokens"),       # ВХОД = вся история + новый вопрос
        "completion_tokens": d.get("completion_tokens"),  # ВЫХОД = ответ модели
        "total_tokens": d.get("total_tokens"),
        "reasoning_tokens": ctd.get("reasoning_tokens"),  # скрытые «мысли» (платим, не видим)
        "cached_tokens": ptd.get("cached_tokens"),        # часть входа отдали из кэша (дешевле)
    }

"""
День 26 — локальная LLM через HTTP API (LM Studio).

Модель Qwen 3.5 9B крутится на нашей машине. Стучимся к ней тем же
пакетом openai, что весь курс использовали для OpenRouter, — меняется
только base_url: не облако, а http://127.0.0.1:1234 (локальный сервер).

Три запроса разной сложности:
  1) простой факт           — видно, как модель отделяет «мысли» от ответа;
  2) задача на рассуждение   — видно, зачем нужна «думающая» модель;
  3) строгий JSON            — проверяем, держит ли модель схему по-настоящему.
"""
import time
import json
from openai import OpenAI

# --- подключение к локальному серверу -------------------------------------
client = OpenAI(
    base_url="http://127.0.0.1:1234/v1",  # дверь, которую поднял LM Studio
    api_key="lm-studio",                   # серверу не нужен, но поле обязано быть непустым
    timeout=180,
)
MODEL = "qwen3.5-9b-mlx"


def ask(title, messages, response_format=None, max_tokens=800, think=True):
    """Один запрос к модели + замер скорости. Печатает мысли и ответ раздельно."""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

    # Qwen 3.5 по умолчанию «думает». Команда /no_think в конце сообщения
    # выключает думание там, где оно не нужно (простой факт, строгий JSON).
    if not think:
        messages = messages[:-1] + [
            {**messages[-1], "content": messages[-1]["content"] + " /no_think"}
        ]

    kwargs = dict(model=MODEL, messages=messages, temperature=0, max_tokens=max_tokens)
    if response_format is not None:          # шлём формат только когда он нужен (№3)
        kwargs["response_format"] = response_format

    t0 = time.time()
    resp = client.chat.completions.create(**kwargs)
    dt = time.time() - t0

    msg = resp.choices[0].message
    thoughts = getattr(msg, "reasoning_content", None)
    # обычно ответ в content; но думающая модель порой кладёт всё в мысли — подстрахуемся
    answer = (msg.content or thoughts or "").strip()
    u = resp.usage

    if thoughts:
        # показываем только начало «размышления», чтобы не заваливать экран
        short = thoughts.strip().replace("\n", " ")
        print(f"\n[мысли модели, {len(thoughts)} символов]: {short[:180]}...")
    print(f"\nОТВЕТ: {answer}")
    print(f"\nfinish_reason={resp.choices[0].finish_reason} | "
          f"{u.completion_tokens} токенов за {dt:.1f} c (~{u.completion_tokens / dt:.1f} ток/с)")
    return answer


# --- Запрос 1: простой факт -----------------------------------------------
ask(
    "ЗАПРОС 1 — простой факт (думание выключено)",
    [{"role": "user", "content": "В каком году человек впервые высадился на Луну? Ответь кратко."}],
    think=False,
)

# --- Запрос 2: задача на рассуждение --------------------------------------
ask(
    "ЗАПРОС 2 — рассуждение по шагам (думание включено)",
    [{"role": "user", "content": (
        "Реши по шагам. У Марка было 3 коробки, в каждой по 8 яблок. "
        "Он отдал другу 5 яблок, а потом купил ещё 2 такие же коробки. "
        "Сколько яблок у Марка теперь?"
    )}],
    max_tokens=1500,  # думающей модели нужен запас, иначе оборвётся на полуслове
)

# --- Запрос 3: строгий JSON (structured output) ---------------------------
# Даём модели схему. Локально LM Studio компилирует её в грамматику,
# и модель физически не может выдать поля мимо схемы — проверим вживую.
person_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "person",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "city": {"type": "string"},
                "profession": {"type": "string"},
            },
            "required": ["name", "age", "city", "profession"],
            "additionalProperties": False,
        },
    },
}
raw = ask(
    "ЗАПРОС 3 — строгий JSON по схеме",
    [{"role": "user", "content": (
        "Извлеки данные о человеке в JSON. Текст: "
        "«Меня зовут Ирина, мне 34 года, я архитектор из Казани.»"
    )}],
    response_format=person_schema,
    think=False,  # для строгого JSON думание только мешает
)

# проверяем, что ответ — валидный JSON и разбирается кодом
try:
    data = json.loads(raw)
    print("\n✔ JSON распарсился. Поле age имеет тип:", type(data["age"]).__name__,
          "| значение:", data["age"])
except Exception as e:
    print("\n[X] JSON НЕ распарсился:", e)

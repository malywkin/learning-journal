import os

from dotenv import load_dotenv
from openai import OpenAI

# 1. Читаем ключ из .env и создаём клиента (OpenRouter совместим с OpenAI SDK —
#    отличаются только base_url и ключ).
load_dotenv()
client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

# Используем gemma: обычная instruct-модель, которая УВАЖАЕТ параметр stop.
# (nemotron-3-super — reasoning-модель: «думает вслух» и stop у этого провайдера
#  игнорирует, поэтому рычаг 3 на ней не проверить.)
MODEL = "google/gemma-4-31b-it:free"


def ask_raw(question: str):
    """Режим БЕЗ ограничений — как в Дне 1: только вопрос пользователя."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": question},
        ],
    )
    return response


def ask_controlled(question: str):
    """Режим С ограничениями — три рычага контроля сразу.

    Рычаг 1 (ФОРМАТ): system-промпт задаёт структуру ответа словами.
    Рычаг 2 (ДЛИНА): max_tokens — жёсткий предел на размер ответа со стороны API.
    Рычаг 3 (ЗАВЕРШЕНИЕ): stop — генерация обрывается, как только встретит эту
                          строку (саму строку в ответ модель НЕ включает).
    """
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            # Рычаг 1: явное описание формата — только числа через запятую, без болтовни.
            {
                "role": "system",
                "content": (
                    "Выводи ответ только числами через запятую, без рассуждений "
                    "и пояснений."
                ),
            },
            {"role": "user", "content": question},
        ],
        max_tokens=600,          # Рычаг 2: потолок размера ответа (страховка).
        stop=["4"],              # Рычаг 3: на счёте «1, 2, 3, …» оборвётся перед «4».
    )
    return response


def show(title: str, response):
    """Печатает ответ и служебные поля — чтобы видеть, что произошло под капотом."""
    choice = response.choices[0]
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(choice.message.content)
    # finish_reason показывает, ПОЧЕМУ генерация остановилась:
    #   "stop"   — модель сама закончила ИЛИ сработала наша stop-строка;
    #   "length" — упёрлись в max_tokens (ответ обрезан принудительно).
    print(f"\n[finish_reason = {choice.finish_reason}]")
    if response.usage:  # сколько токенов реально потратили на ответ
        print(f"[completion_tokens = {response.usage.completion_tokens}]")


if __name__ == "__main__":
    # Спрашиваем вопрос у тебя один раз (как в Дне 1) и гоняем его в ОБА режима —
    # так сравнение честное: один и тот же вопрос, разный уровень контроля.
    question = input("Ваш вопрос к LLM: ")
    show("БЕЗ ОГРАНИЧЕНИЙ (raw)", ask_raw(question))
    show("С ОГРАНИЧЕНИЯМИ (формат + длина + стоп)", ask_controlled(question))

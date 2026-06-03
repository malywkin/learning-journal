import os

from dotenv import load_dotenv
from openai import OpenAI

# 1. Читаем секреты из файла .env в переменные окружения
load_dotenv()

# 2. Создаём клиента. OpenRouter совместим с OpenAI SDK —
#    отличие только в base_url (адрес шлюза) и ключе.
client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

# 3. Спрашиваем вопрос у пользователя в консоли (это и есть CLI-интерфейс)
question = input("Ваш вопрос к LLM: ")

# 4. Отправляем запрос в модель и получаем ответ
response = client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b:free",
    messages=[
        {"role": "user", "content": question},
    ],
)

# 5. Достаём текст ответа и выводим в консоль
print("\nОтвет модели:\n")
print(response.choices[0].message.content)

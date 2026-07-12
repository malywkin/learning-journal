"""День 27 — телеграм-бот на локальной LLM (без RAG).

Задание дня: реальное приложение → шлёт запрос в локальную модель → показывает
ответ → работает без облака. Здесь приложение — телеграм-бот; мотор — qwen3.5-9b
в LM Studio (localhost:1234). Никакого поиска и RAG: вопрос уходит прямо в модель.
(Связка RAG + локальная модель + сравнение с облаком — это уже день 28, соседняя папка.)

Одна тонкость, разобранная в day28: модель — reasoning, и на MLX-сборке залипает
во внутреннем монологе (пустой ответ, ~минута). Гасим это префиллом пустого блока
<think></think> — подсовываем как её же реплику, и она сразу пишет ответ (~3 с).

Запуск:  ../day21/.venv/bin/python task27.py   (токен из .env)
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from openai import OpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

# --- .env (токен не хардкодим) ---
for _line in (Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in _line and not _line.startswith("#"):
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# --- локальная модель через OpenAI-совместимый сервер LM Studio ---
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", timeout=120)
MODEL = "qwen3.5-9b-mlx"
NOTHINK = {"role": "assistant", "content": "<think></think>"}   # гасим reasoning
SYSTEM = "Ты — дружелюбный помощник. Отвечай кратко и понятно, по-русски."

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("day27")


def ask_local(question: str) -> str:
    """Один прямой вызов локальной модели — без поиска, без RAG."""
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            NOTHINK]                                # префилл гасит внутренний монолог
    r = client.chat.completions.create(
        model=MODEL, temperature=0.3, max_tokens=500, messages=msgs)
    return (r.choices[0].message.content or "").strip() or "(модель вернула пустой ответ)"


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я работаю на локальной модели — прямо на этом компьютере, без облака. "
        "Спроси что угодно.")


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = (update.message.text or "").strip()
    if not q:
        return
    log.info("вопрос: %s", q)
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    t0 = time.time()
    ans = await asyncio.to_thread(ask_local, q)     # блокирующий вызов — в поток
    dt = time.time() - t0
    await update.message.reply_text(f"{ans}\n\n— локальная qwen-9b · {dt:.0f} с")


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("бот запущен (локальная LLM, без RAG)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

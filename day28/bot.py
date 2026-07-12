"""День 27 — телеграм-бот поверх нашего RAG-конвейера, полностью на ЛОКАЛЬНОЙ модели.

Задание дня: реальное приложение → шлёт запрос в локальную LLM → показывает ответ →
без облачных моделей. Здесь приложение — телеграм-бот; ядро — конвейер дней 21–24
(поиск → реранк → порог → контракт → проверка цитат → судья); мотор — qwen3.5-9b
в LM Studio (local_llm.activate переключил grounded на localhost + гашение thinking).

Приватность (уговор дня): МОДЕЛЬ локальна, облако не дёргается. Но текст сообщений
идёт через серверы Telegram — поэтому бот для нейтральных вопросов о сне/уходе,
а не для приватных данных о конкретном ребёнке.

Запуск:  ../day21/.venv/bin/python bot.py   (токен и LM_LOCAL берутся из .env)
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import local_llm

# --- .env (токен не хардкодим) ---
for _line in (Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in _line and not _line.startswith("#"):
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("day27-bot")

import grounded as gr         # noqa: E402  тот же модуль, что патчит local_llm

# Два мотора одного и того же RAG-конвейера — переключаются кнопкой (день 28).
ENGINES = {
    "local": ("🖥 Локальная qwen-9b", local_llm.activate_local),
    "cloud": ("☁️ DeepSeek облако", local_llm.activate_cloud),
}
DEFAULT_ENGINE = "local"

# Ярлык вердикта судьи → человеку понятная пометка о доверии
VERDICT_RU = {"supported": "✔ подтверждено источниками",
              "partial": "◐ частично подтверждено",
              "unsupported": "✘ не подтверждено источниками",
              "unknown": "? проверку провести не удалось"}


def _keyboard(active: str) -> InlineKeyboardMarkup:
    """Две кнопки выбора мотора; у активного — галочка."""
    row = []
    for key, (label, _) in ENGINES.items():
        mark = "● " if key == active else "○ "
        row.append(InlineKeyboardButton(mark + label, callback_data=f"eng:{key}"))
    return InlineKeyboardMarkup([row])


def format_reply(r: dict) -> str:
    """Результат конвейера → сообщение для телеграма: ответ + источники + доверие."""
    # Отказ — двух видов: по порогу реранкера (ничего не прошло) ИЛИ модель
    # прочитала подтянутые куски и не нашла ответа (grounding, день 24). В обоих
    # случаях источник показывать нельзя — мы на него не опёрлись (баг: было
    # «В источниках нет» + раздел рядом, ловил F на кривом вопросе).
    if r.get("abstained") or r.get("status") == "model_abstained":
        return ("🤷 В моих источниках нет ответа на это.\n"
                "Я отвечаю только по книге о детском сне — спросите про сон, "
                "плач, безопасность сна, совместный сон.")

    lines = [r["answer"]]

    # источники (разделы, на которые опёрлись)
    sections = []
    for c in r.get("kept", []):
        s = (c.get("section") or "").strip()
        if s and s not in sections:
            sections.append(s)
    if sections:
        lines.append("\n📚 Источники: " + "; ".join(sections[:3]))

    # пометка о доверии (наш предохранитель дня 24)
    faith = r.get("faithfulness")
    if r.get("status") == "unverifiable":
        lines.append("⚠ Ответ не удалось подтвердить дословной цитатой — отношусь осторожно.")
    elif faith:
        lines.append(VERDICT_RU.get(faith.get("verdict"), ""))

    return "\n".join(x for x in lines if x)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.chat_data.setdefault("engine", DEFAULT_ENGINE)
    await update.message.reply_text(
        "Привет! Я ассистент по детскому сну на нашем RAG — один и тот же поиск, "
        "два мотора генерации: локальная модель на этом компьютере или облако DeepSeek.\n\n"
        "Выберите мотор кнопкой и задайте вопрос. Задайте один и тот же вопрос обоим — "
        "увидите разницу в скорости и качестве прямо здесь.\n"
        "Отвечаю строго по источнику и честно говорю «не знаю», если ответа в нём нет.",
        reply_markup=_keyboard(ctx.chat_data["engine"]))


async def on_engine(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Нажата кнопка выбора мотора."""
    query = update.callback_query
    engine = query.data.split(":", 1)[1]
    ctx.chat_data["engine"] = engine
    await query.answer(f"Мотор: {ENGINES[engine][0]}")
    await query.edit_message_reply_markup(reply_markup=_keyboard(engine))


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = (update.message.text or "").strip()
    if not q:
        return
    engine = ctx.chat_data.get("engine", DEFAULT_ENGINE)
    label, switch = ENGINES[engine]
    log.info("вопрос [%s]: %s", engine, q)
    switch()                                      # переключаем мотор конвейера
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    # конвейер блокирующий (эмбеддер/реранкер/LLM) — уводим в поток, не морозим бота
    t0 = time.time()
    r = await asyncio.to_thread(gr.answer, q)
    dt = time.time() - t0
    header = f"{label} · {dt:.0f} с\n\n"
    await update.message.reply_text(header + format_reply(r),
                                    reply_markup=_keyboard(engine))


def _warmup() -> None:
    """Прогрев тяжёлых моделей (эмбеддер bge-m3 + cross-encoder) ДО опроса Telegram,
    чтобы первый живой вопрос не ждал ~20 с загрузки."""
    log.info("прогрев эмбеддера и реранкера…")
    gr.retrieve("сон новорождённого", k=3)
    from rerank import _model as _rr
    _rr()
    log.info("прогрев готов")


def main() -> None:
    _warmup()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_engine, pattern=r"^eng:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("бот запущен (Ctrl+C для остановки)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

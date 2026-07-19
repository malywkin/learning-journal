"""
День 35 — доставка дайджеста в Telegram (это OUTPUT пайплайна по §12).

ПРИВАТНОСТЬ И БЕЗОПАСНОСТЬ (уговор Дня 35, разобрано с F):
Возраст ребёнка — приватный факт, но он не тайна: F и так в мессенджерах. Реальные риски —
не «текст ушёл», а дыры в коде, поэтому:
  • бот работает ТОЛЬКО на отправку. Он НЕ гоняет модель на входящие сообщения (в отличие
    от бота Дня 28) и не исполняет команд-действий — минимальная поверхность атаки;
  • всего две сервисные команды: /start (узнать свой chat_id) и /digest (прислать дайджест
    сейчас, себе). Никакого произвольного ввода в систему;
  • токен и chat_id — из .env, в git не идут; агент дайджеста умеет только читать корпус и
    писать свою заметку (нет разрушительных инструментов → инъекция из Дня 33 обезврежена).

Реюз: python-telegram-bot 22.8 и каркас из Дня 28 (там бот уже поднимался). Здесь он проще —
без переключателей и without обработки свободного текста.
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("day35-bot")

# Telegram режет длинные сообщения (лимит ~4096 символов) — бьём на части по абзацам.
TG_LIMIT = 3800


def _split(text: str) -> list[str]:
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > TG_LIMIT:
            if cur:
                parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


async def send_digest(text: str, chat_id: str | None = None) -> None:
    """Отправить готовый текст дайджеста в Telegram. Зовётся планировщиком (§12 OUTPUT).
    Отдельная функция, чтобы её мог дёргать и cron, и ручная команда /digest."""
    chat_id = chat_id or config.TG_CHAT_ID
    if not config.TG_TOKEN or not chat_id:
        log.warning("нет TELEGRAM_TOKEN/CHAT_ID — отправка пропущена (ключи/доступы, §задание)")
        return
    from telegram import Bot
    bot = Bot(config.TG_TOKEN)
    for part in _split(text):
        await bot.send_message(chat_id=chat_id, text=part)
    log.info("дайджест отправлен в chat_id=%s", chat_id)


# ---------- сервисные команды (только эти две; свободный текст НЕ обрабатываем) ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    await update.message.reply_text(
        "🍼 Родительский AI-дайджест\n\n"
        "ЗАДАЧА, которую решаю:\n"
        "Раз в неделю сам готовлю короткую выжимку по возрасту ребёнка — сейчас это неделя "
        "беременности, после рождения переключаюсь на недели жизни. Беру только доказательные "
        "гайдлайны NHS и CDC: развитие, кормление, сон, тревожные признаки. Без страшилок и "
        "без выдуманных чисел.\n\n"
        "КАК УЧАСТВУЕТ AI (по шагам):\n"
        "1. Планировщик будит систему по расписанию (раз в неделю).\n"
        "2. Возраст ребёнка превращается в вопросы по рубрикам.\n"
        "3. AI ищет ответ в корпусе гайдлайнов (поиск + реранкер) и отвечает ТОЛЬКО из "
        "найденных источников.\n"
        "4. Каждая цитата сверяется с текстом источника; слабый ответ отбрасывается, а не "
        "выдумывается.\n"
        "5. Готовая заметка со ссылками приходит сюда.\n\n"
        f"Твой chat_id: {cid} — впиши его в .env как TELEGRAM_CHAT_ID, чтобы получать по "
        "расписанию.\nКоманда /digest — прислать свежий дайджест прямо сейчас.")


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Собираю дайджест по источникам…")
    res = await asyncio.to_thread(digest.build_digest)     # тяжёлый RAG — в поток, не морозим бота
    for part in _split(res["telegram"]):
        await update.message.reply_text(part)


def run_bot() -> None:
    """Поднять бота в режиме опроса (для /start и /digest). Для авто-рассылки см. run.py."""
    if not config.TG_TOKEN:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в .env")
    app = Application.builder().token(config.TG_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    log.info("бот запущен (только /start и /digest; свободный текст не обрабатывается)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()

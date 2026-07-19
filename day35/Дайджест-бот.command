#!/bin/bash
# Родительский дайджест — Telegram-бот (День 35). Двойной клик в Finder → бот жив.
# В боте: /start — узнать свой chat_id; /digest — прислать свежий дайджест сейчас.
# Для авто-рассылки раз в неделю: ../day21/.venv/bin/python run.py --serve
cd "$(dirname "$0")"
echo "Запускаю дайджест-бота… (окно не закрывать; Ctrl+C — остановить)"
exec ../day21/.venv/bin/python bot.py

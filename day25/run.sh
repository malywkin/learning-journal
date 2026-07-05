#!/bin/bash
# День 25 — запуск веб-демо мини-чата. Одна команда.
#   bash run.sh
# Потом открой в браузере:  http://127.0.0.1:8250
cd "$(dirname "$0")"
exec ../day21/.venv/bin/uvicorn app:app --port 8250 --log-level warning

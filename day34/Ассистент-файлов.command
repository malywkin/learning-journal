#!/bin/bash
# День 34 — запускалка ассистента файлов. Двойной клик → сервер + браузер (не терминал).
cd "$(dirname "$0")"
PY="/Users/v/Desktop/Life/Education/Tasks/day21/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

echo "Поднимаю ассистента файлов на http://127.0.0.1:8034 …"
"$PY" app.py &
SRV=$!
# ждём, пока порт ответит, потом открываем окно
for i in $(seq 1 20); do
  curl -s -m 1 http://127.0.0.1:8034/project >/dev/null 2>&1 && break
  sleep 0.4
done
open "http://127.0.0.1:8034"
echo "Окно открыто. Закройте это окно терминала, чтобы остановить сервер."
wait $SRV

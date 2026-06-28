"""
Единый запуск витрины Дня 20: поднимает ТРИ MCP-сервера подпроцессами (reddit/storage/utils),
ждёт, пока они встанут, открывает браузер и стартует FastAPI-витрину. Глушит всё при выходе.

  python run.py   →  http://127.0.0.1:8100
                     reddit :8101 · storage :8102 · utils :8103
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

HERE = Path(__file__).parent
SERVERS = ["reddit_server.py", "storage_server.py", "utils_server.py"]

if __name__ == "__main__":
    procs = [subprocess.Popen([sys.executable, str(HERE / s)]) for s in SERVERS]
    try:
        time.sleep(2.5)  # дать всем трём серверам подняться
        webbrowser.open("http://127.0.0.1:8100")
        uvicorn.run("app:app", host="127.0.0.1", port=8100, app_dir=str(HERE))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait()

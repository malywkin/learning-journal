"""
Удобный единый запуск веб-витрины Дня 17: поднимает MCP-сервер подпроцессом,
открывает браузер и стартует FastAPI. Глушит сервер при выходе.

  python run.py     →  http://127.0.0.1:8016
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

HERE = Path(__file__).parent

if __name__ == "__main__":
    server = subprocess.Popen([sys.executable, str(HERE / "mcp_server.py")])
    try:
        time.sleep(2)  # дать MCP-серверу подняться
        webbrowser.open("http://127.0.0.1:8016")
        uvicorn.run("app:app", host="127.0.0.1", port=8016, app_dir=str(HERE))
    finally:
        server.terminate()
        server.wait()

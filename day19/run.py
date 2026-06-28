"""
Единый запуск витрины Дня 19: поднимает MCP-сервер (три инструмента) подпроцессом,
открывает браузер и стартует FastAPI. Глушит сервер при выходе.

  python run.py     →  http://127.0.0.1:8030     (MCP-сервер слушает на :8029)
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
        webbrowser.open("http://127.0.0.1:8030")
        uvicorn.run("app:app", host="127.0.0.1", port=8030, app_dir=str(HERE))
    finally:
        server.terminate()
        server.wait()

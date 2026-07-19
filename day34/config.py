"""
День 34 — конфиг движка «ассистент для работы с файлами проекта».

Наследуем универсальность Дня 31: всё, что привязано к конкретному проекту, живёт
здесь и только здесь — путь к проекту. Наведи PROJECT_ROOT на другой репозиторий,
и тот же мотор станет ассистентом-редактором по нему, код трогать не надо.

По умолчанию целимся в подопытный sample_project (воспроизводимый прогон, записи
не трогают отслеживаемые файлы курса). Можно переопределить переменной окружения.
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent                 # .../Tasks/day34

# ── КАКОЙ проект редактируем (единственное, что меняется под другой репо) ──
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(BASE / "sample_project"))).resolve()

# Файл с правилами/инвариантами проекта (сценарий 3). Относительно PROJECT_ROOT.
RULES_FILE = "RULES.md"

# ── Клетка §11: что НЕ трогать (ни читать, ни тем более писать) ──
# .env и секреты — сюда агенту доступа нет ни на чтение, ни на запись.
IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".idea",
               ".vscode", "output"}
IGNORE_FILE_SUFFIX = {".pyc", ".db", ".wav", ".mp4", ".mov", ".parquet", ".png", ".jpg"}
IGNORE_FILE_NAMES = {".env", ".DS_Store", "notes.json"}

# ── Модель: DeepSeek основной, локальный qwen3.5 (LM Studio) запасной (§14) ──
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
LOCAL_BASE_URL = "http://localhost:1234/v1"            # LM Studio (Дни 26–30)
LOCAL_MODEL = "qwen3.5"
MAX_TOOL_HOPS = 10        # предохранитель tool-use цикла: не крутиться вечно


if __name__ == "__main__":
    print(f"PROJECT_ROOT = {PROJECT_ROOT}")
    print(f"существует:    {PROJECT_ROOT.is_dir()}")
    print(f"RULES_FILE:    {(PROJECT_ROOT / RULES_FILE).is_file()}")

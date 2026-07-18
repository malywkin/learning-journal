"""
День 31 — конфиг движка «ассистент разработчика».

ГЛАВНОЕ: движок УНИВЕРСАЛЬНЫЙ. Всё, что привязано к конкретному проекту, живёт
здесь и только здесь — путь к репозиторию + маска «что считать документацией».
Наведи эти две ручки на другой репозиторий (или на юр./деловые доки) — и тот же
мотор станет ассистентом по нему, код трогать не надо.

Приём наследуем с Дня 22 (rag_core.py): настройка вынесена наружу (INDEX_DB,
пороги через os.getenv), логика внутри неизменна. Одно ядро — много витрин.
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent            # .../Tasks/day31

# ── ЧТО за проект обслуживаем (единственное, что меняется под другой репо) ──
# По умолчанию — наш курсовой репозиторий learning-journal (Tasks/ = git-корень,
# ветка main, remote github.com/malywkin/learning-journal). Можно переопределить
# переменной окружения REPO_ROOT, не трогая код.
REPO_ROOT = Path(os.getenv("REPO_ROOT", str(BASE.parent))).resolve()

# Что считать «документацией» для инструмента «поиск по докам» (маска, не список).
# Markdown-файлы проекта: обзор, задания, конспекты прогресса, README.
DOC_GLOBS = [
    "OVERVIEW.md",       # обзор проекта (собираем на узле 2)
    "PROGRESS.md",       # трекер прогресса — тоже документация проекта
    "**/task.md",        # формулировки заданий по дням
    "**/takeaways.md",   # выводы по дням (наш «второй мозг» курса)
    "README*.md",
]

# Что НЕ трогать при агентном чтении файлов (шум, тяжесть, секреты).
IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".idea",
               ".vscode", "output", "notes"}
IGNORE_FILE_SUFFIX = {".pyc", ".db", ".wav", ".mp4", ".mov", ".parquet", ".csv"}
IGNORE_FILE_NAMES = {".env", ".DS_Store", "memory.json", "memory.db"}

# ── ГДЕ храним индекс доков (свой, day21/index.db не трогаем — там книга) ──
INDEX_DB = BASE / "docs_index.db"
EMBED_MODEL = "BAAI/bge-m3"        # тот же эмбеддер, что во всех RAG-днях (21–25)

# ── Модель: DeepSeek основной, локальный qwen3.5 (LM Studio) запасной ──
# Ключ и адрес читаются в llm.py из .env; здесь — только имена и границы.
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
LOCAL_BASE_URL = "http://localhost:1234/v1"       # LM Studio (Дни 26–30)
LOCAL_MODEL = "qwen3.5"
MAX_TOOL_HOPS = 8          # предохранитель tool-use цикла: не крутиться вечно


def docs_paths() -> list[Path]:
    """Собрать реальные пути доков по маске (для индексации на узле 3)."""
    seen, out = set(), []
    for pat in DOC_GLOBS:
        for p in sorted(REPO_ROOT.glob(pat)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


if __name__ == "__main__":
    # Быстрая самопроверка конфига (не прод, для нас): куда целимся и сколько доков.
    print(f"REPO_ROOT = {REPO_ROOT}")
    print(f"INDEX_DB  = {INDEX_DB}")
    docs = docs_paths()
    print(f"Документов под маску: {len(docs)}")
    for p in docs[:12]:
        print("  ", p.relative_to(REPO_ROOT))
    if len(docs) > 12:
        print(f"   … ещё {len(docs) - 12}")

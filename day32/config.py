"""
День 32 — конфиг AI-ревьюера кода (пайплайн на GitHub Actions).

Принцип тот же, что весь курс: всё, что привязано к конкретному месту/провайдеру,
живёт здесь, логика — в других файлах. Наводишь ручки — тот же мотор ревьюит
другой репозиторий. Наследуем вынос настроек наружу с Дней 22/31.

ВАЖНО про облако: на раннере GitHub (чужая одноразовая машина) нашего локального
qwen из Дней 26-31 НЕТ. Поэтому запасной провайдер тут облачный — OpenRouter,
а не LM Studio. Это §14 конспекта: fallback должен быть реально доступен там,
где крутится пайплайн.
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent            # .../Tasks/day32
REPO_ROOT = Path(os.getenv("REPO_ROOT", str(BASE.parent))).resolve()  # Tasks/ = git-корень

# ── Правила проекта («брендбук»), которые робот кладёт перед глазами ──
REVIEW_GUIDE = BASE / "REVIEW_GUIDE.md"

# ── Провайдеры модели: цепочка попыток DeepSeek → OpenRouter (оба облачные) ──
# Ключи читаем из окружения (в CI — из секрета репозитория; локально — из .env).
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL    = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")

# ── Удержание бюджета/скорости (§15): не суём весь проект, режем контекст ──
MAX_DIFF_CHARS = int(os.getenv("MAX_DIFF_CHARS", "24000"))   # diff крупнее — обрежем
MAX_CODE_CHARS = int(os.getenv("MAX_CODE_CHARS", "6000"))    # добор кода вокруг правки
MAX_RETRIES    = int(os.getenv("MAX_RETRIES", "3"))          # §14: максимум 3 попытки

# ── Что считать «документацией проекта» для добора контекста (RAG, лёгкий путь) ──
# Меняли day07/memory.py → подтянем day07/takeaways.md и day07/task.md.
DOC_SUFFIXES = ("takeaways.md", "task.md")
GLOBAL_DOCS = ["PROGRESS.md"]           # общий трекер проекта — тоже правила/контекст
IGNORE_PATH_PARTS = {".git", ".venv", "__pycache__", "node_modules"}

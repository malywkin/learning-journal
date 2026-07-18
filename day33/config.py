"""
День 33 — конфиг ассистента поддержки. Всё, что привязано к КОНКРЕТНОМУ продукту,
живёт здесь и только здесь (приём универсальности с Дня 31): папка с FAQ + файл с
тикетами. Наведи эти две ручки на реальный сервис (или на MCP настоящей CRM) — тот же
мотор станет поддержкой по нему, код не трогаем.

Демо-продукт: «Поток» — вымышленный подписочный онлайн-сервис заметок и задач
(тарифы Free / Personal / Team / Business). FAQ — наш собственный текст (публикуемый),
тикеты — обезличенные демо-карточки.
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent            # .../Tasks/day33

# ── ЧТО за продукт обслуживаем (единственное, что меняется под другой сервис) ──
PRODUCT_NAME = "Поток"

# База знаний для инструмента «поиск по FAQ» (наш RAG Дней 21–24).
FAQ_DIR = BASE / "faq"
# docs_tool режет пути относительно REPO_ROOT — целим его в саму папку FAQ,
# тогда source в ответе = имя файла (auth.md, billing.md …).
REPO_ROOT = FAQ_DIR
DOC_GLOBS = ["*.md"]

# База пользователей/тикетов, которую отдаёт наш MCP-сервер (замена CRM).
TICKETS_JSON = BASE / "tickets.json"

# ── Где храним индекс FAQ (свой, чужие индексы прошлых дней не трогаем) ──
INDEX_DB = BASE / "faq_index.db"
EMBED_MODEL = "BAAI/bge-m3"        # тот же эмбеддер, что во всех RAG-днях (21–25)

# Порог «нашлось ли в FAQ» (score кросс-энкодера Дня 23, 0..1). Ниже — считаем, что
# релевантного в базе нет, и предлагаем эскалацию, а НЕ выдумываем ответ (приём Дня 24).
FAQ_THRESHOLD = 0.30

# ── Модель: DeepSeek основной, локальный qwen3.5 (LM Studio) запасной (§14) ──
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
LOCAL_BASE_URL = "http://localhost:1234/v1"       # LM Studio (Дни 26–30)
LOCAL_MODEL = "qwen3.5"
MAX_TOOL_HOPS = 8          # предохранитель tool-use цикла: не крутиться вечно


def docs_paths() -> list[Path]:
    """Собрать реальные пути FAQ-файлов по маске (для индексации)."""
    seen, out = set(), []
    for pat in DOC_GLOBS:
        for p in sorted(REPO_ROOT.glob(pat)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


if __name__ == "__main__":
    print(f"PRODUCT      = {PRODUCT_NAME}")
    print(f"FAQ_DIR      = {FAQ_DIR}")
    print(f"TICKETS_JSON = {TICKETS_JSON}")
    docs = docs_paths()
    print(f"FAQ-файлов под маску: {len(docs)}")
    for p in docs:
        print("  ", p.name)

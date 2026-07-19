"""
День 35 (финал недели 7) — конфиг родительского дайджеста.

Движок УНИВЕРСАЛЬНЫЙ, как весь капстоун (День 31): всё, что привязано к «этому»
дайджесту, живёт здесь. Наведи две ручки — папку корпуса и даты ребёнка — и тот же
мотор поедет по другому корпусу/другой семье, код трогать не надо.

Ничего с нуля: имена моделей, эмбеддер и приём «настройка наружу, логика внутри» —
ровно из config Дней 24/31. Индекс — свой (corpus_index.db), чужие не трогаем.

ПРИВАТНОСТЬ (уговор с F, День 35): даты ребёнка — приватный факт, поэтому они
читаются из .env и НЕ коммитятся. В публичный репозиторий (learning-journal) идёт
только код + корпус публичных гайдлайнов NHS/CDC (их лицензия это прямо разрешает).
"""
import os
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent            # .../Tasks/day35

# ---------- .env (даты и ключи не в коде, не в git) ----------
_ENV = BASE / ".env"
for _line in _ENV.read_text().splitlines() if _ENV.exists() else []:
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# ── ЧТО за корпус обслуживаем (единственное, что меняется под другую тему) ──
# Папка с публичными гайдлайнами (.md). По умолчанию — corpus/ рядом.
CORPUS_DIR = Path(os.getenv("CORPUS_DIR", str(BASE / "corpus"))).resolve()
DOC_GLOBS = ["*.md"]                    # весь корпус — markdown-файлы гайдлайнов
INDEX_DB = BASE / "corpus_index.db"     # свой индекс (чужие дни не трогаем)
EMBED_MODEL = "BAAI/bge-m3"             # тот же эмбеддер, что во всех RAG-днях (21–33)

# Индексатор Дня 31 (docs_tool.py) ждёт эти два имени — даём их, наведя на корпус.
# Так переиспользуем его код без единой правки (реюз через совместимость конфига).
REPO_ROOT = CORPUS_DIR


def docs_paths() -> list[Path]:
    """Собрать пути гайдлайнов по маске (для индексации в docs_tool.build_index)."""
    seen, out = set(), []
    for pat in DOC_GLOBS:
        for p in sorted(CORPUS_DIR.glob(pat)):
            if p.name == "SOURCES.md":          # мета-сводка, не гайдлайн — не индексируем
                continue
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out

# ── Даты ребёнка (приватные, из .env) ──
# Логика фаз в age.py: если известна дата рождения → режим «недели жизни»;
# иначе считаем по сроку → режим «неделя беременности». Сейчас (июль-2026) ребёнок
# ещё не родился: BABY_BIRTH_DATE пуст, работает пренатальный режим по BABY_DUE_DATE.
def _parse_date(name: str) -> date | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)          # ГГГГ-ММ-ДД
    except ValueError:
        return None

BABY_DUE_DATE = _parse_date("BABY_DUE_DATE")     # предполагаемая дата родов (ПДР)
BABY_BIRTH_DATE = _parse_date("BABY_BIRTH_DATE")  # фактическая дата рождения (когда наступит)

# ── Модель: DeepSeek основной, OpenRouter/локальный qwen — запасные (§14) ──
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
LOCAL_BASE_URL = "http://localhost:1234/v1"      # LM Studio (Дни 26–30)
LOCAL_MODEL = "qwen3.5"

# ── RAG-пороги (наследуем калибровку Дня 24) ──
CANDIDATES = 18       # сколько поиск отдаёт реранкеру
FINAL_K = 5           # сколько кусков уходит модели после фильтра
THRESHOLD = 0.54      # порог-отказ по score реранкера (калибровано на golden set 05.07)
FUZZ_PASS = 90        # порог дословности цитаты (rapidfuzz)

# ── Доставка (Telegram; приватность — уговор Дня 35) ──
# Бот работает ТОЛЬКО на отправку дайджеста, входящие команды-действия не исполняет
# (минимальная поверхность атаки). Токен и chat_id — из .env.
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Куда складываем готовые заметки (архив на диске — второй, приватный выход).
DIGEST_DIR = BASE / "digests"
JOBSTORE_DB = BASE / "schedule.sqlite"           # расписание планировщика на диске (День 18)


if __name__ == "__main__":
    print(f"CORPUS_DIR = {CORPUS_DIR} (файлов: {len(list(CORPUS_DIR.glob('*.md'))) if CORPUS_DIR.exists() else 0})")
    print(f"INDEX_DB   = {INDEX_DB.name}")
    print(f"ПДР        = {BABY_DUE_DATE}")
    print(f"Рождение   = {BABY_BIRTH_DATE or '(ещё не родился → режим беременности)'}")
    print(f"Telegram   = токен {'есть' if TG_TOKEN else 'НЕТ'}, chat_id {'есть' if TG_CHAT_ID else 'НЕТ'}")

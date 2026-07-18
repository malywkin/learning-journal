"""
День 31 — инструмент №3 роутера: АГЕНТНОЕ ЧТЕНИЕ файлов (System Tools, §8).

Честный фронтир из брифа: для маленького репо лидеры (Claude Code, Cline) ходят прямо
в файлы grep/read по требованию, а не в заранее собранный вектор. Три функции:
  - list_files  — карта репозитория (какие файлы есть);
  - grep_repo   — поиск строки/шаблона по коду и докам СЕЙЧАС (точное попадание);
  - read_file   — прочитать конкретный файл (кусок), чтобы ответить дословно.

Безопасность §11 (sandbox): всё строго read-only и заперто внутри config.REPO_ROOT.
Наружу за пределы репо не выходим (jail), .env и бинарники/тяжёлое не отдаём (маска
config.IGNORE_*). Тот же принцип, что наша project Bash sandbox: опасное просто недоступно.
"""
import os
import re
from pathlib import Path

import config

MAX_READ_BYTES = 12_000        # не вываливаем гигантские файлы в контекст модели
MAX_GREP_HITS = 40


def _ignored(p: Path) -> bool:
    """Файл под маской игнора (секрет/бинарник/мусор) или лежит в игнор-папке?"""
    if p.name in config.IGNORE_FILE_NAMES:
        return True
    if p.suffix.lower() in config.IGNORE_FILE_SUFFIX:
        return True
    return any(part in config.IGNORE_DIRS for part in p.parts)


def _safe(relpath: str) -> Path | None:
    """Разрешить путь ТОЛЬКО внутри репо и не секрет. Иначе None (клетка §11)."""
    try:
        p = (config.REPO_ROOT / relpath).resolve()
    except Exception:
        return None
    if config.REPO_ROOT not in p.parents and p != config.REPO_ROOT:
        return None                                    # попытка выйти за репо (../..)
    if not p.is_file() or _ignored(p):
        return None
    return p


def _walk() -> list[Path]:
    """Все текстовые файлы репо, кроме игнор-папок/масок. os.walk с обрезкой веток
    ДО спуска — не заходим в .venv/.git и т.п. (иначе обход десятков тысяч файлов)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(config.REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in config.IGNORE_DIRS]  # обрезаем ветку
        for name in filenames:
            p = Path(dirpath) / name
            if not _ignored(p):
                out.append(p)
    return out


# ---------- 1. Карта репозитория ----------
def list_files(subdir: str = ".", limit: int = 200) -> dict:
    """Список файлов репозитория (относительные пути). subdir — сузить до подпапки."""
    root = (config.REPO_ROOT / subdir).resolve()
    if config.REPO_ROOT not in root.parents and root != config.REPO_ROOT:
        return {"error": "путь вне репозитория"}
    files = [str(p.relative_to(config.REPO_ROOT))
             for p in _walk() if str(p).startswith(str(root))]
    files.sort()
    return {"count": len(files), "files": files[:limit],
            "truncated": len(files) > limit}


# ---------- 2. Поиск по коду и докам (grep) ----------
def grep_repo(pattern: str, glob: str = "*", max_hits: int = MAX_GREP_HITS) -> dict:
    """Найти строки, совпавшие с pattern (регэксп), по файлам репо. glob — сузить (напр. *.py).
    Возвращает попадания {file, line, text} — точное место, а не «по смыслу»."""
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"плохой шаблон: {e}"}
    hits, scanned = [], 0
    for p in _walk():
        if glob != "*" and not p.match(glob):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append({"file": str(p.relative_to(config.REPO_ROOT)),
                             "line": i, "text": line.strip()[:200]})
                if len(hits) >= max_hits:
                    return {"pattern": pattern, "scanned_files": scanned,
                            "hits": hits, "truncated": True}
    return {"pattern": pattern, "scanned_files": scanned, "hits": hits, "truncated": False}


# ---------- 3. Прочитать конкретный файл ----------
def read_file(relpath: str, max_bytes: int = MAX_READ_BYTES) -> dict:
    """Прочитать текстовый файл репозитория (в клетке §11). Крупный — обрезаем."""
    p = _safe(relpath)
    if p is None:
        return {"error": f"нельзя прочитать '{relpath}' (вне репо, секрет или не файл)"}
    data = p.read_text(encoding="utf-8", errors="ignore")
    truncated = len(data) > max_bytes
    return {"file": relpath, "truncated": truncated,
            "text": data[:max_bytes], "bytes": len(data)}


if __name__ == "__main__":
    print("list_files day31:", list_files("day31")["files"])
    g = grep_repo(r"def rag_answer", glob="*.py")
    print("\ngrep 'def rag_answer':", [(h["file"], h["line"]) for h in g["hits"]])
    r = read_file("day31/config.py")
    print(f"\nread config.py: {r['bytes']} байт, обрезано={r['truncated']}")
    print("jail-тест (выход за репо):", read_file("../CLAUDE.md").get("error"))

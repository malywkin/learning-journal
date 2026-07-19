"""
День 34 — файловые инструменты ассистента: ЧТЕНИЕ (с Дня 31) + ЗАПИСЬ (новое).

Read-часть (list_files / grep_repo / read_file) перенесена с Дня 31: агентное чтение
в клетке §11 — заперто внутри PROJECT_ROOT, .env и бинарники не отдаём.

Write-часть — новое ядро дня, собрано по брифу 2026:
  * формат правки = search/replace (propose_edit): модель шлёт old_str/new_str, код
    находит РОВНО ОДНО точное совпадение и заменяет — так работает официальный
    str_replace-инструмент Anthropic; надёжнее номеров строк на слабой модели.
  * diff для показа человеку строит НАШ код (difflib.unified_diff), а не модель.
  * НИЧЕГО не пишем сразу: propose_* только готовят правку и возвращают diff.
    Реальная запись — отдельным шагом apply_change ПОСЛЕ подтверждения человека (§11/§14).
  * запись атомарна: temp-файл рядом + os.replace (приём Дня 7); обрыв не бьёт файл.
  * клетка на запись строже, чем на чтение: писать нельзя в .env/секреты и вне корня.
"""
import difflib
import os
import re
import tempfile
from pathlib import Path

import config

MAX_READ_BYTES = 16_000
MAX_GREP_HITS = 60
ROOT = config.PROJECT_ROOT


# ═══════════════════════ клетка §11 (общая) ═══════════════════════
def _ignored(p: Path) -> bool:
    if p.name in config.IGNORE_FILE_NAMES:
        return True
    if p.suffix.lower() in config.IGNORE_FILE_SUFFIX:
        return True
    return any(part in config.IGNORE_DIRS for part in p.parts)


def _inside_root(p: Path) -> bool:
    """Путь строго внутри PROJECT_ROOT (после resolve — .. и симлинки развёрнуты).
    ВАЖНО: os.path.join/‘/’ сами не защищают от ../ — проверяем ПОСЛЕ resolve (бриф)."""
    try:
        p = p.resolve()
    except Exception:
        return False
    return p == ROOT or ROOT in p.parents


def _safe_read(relpath: str) -> Path | None:
    p = (ROOT / relpath)
    if not _inside_root(p):
        return None
    p = p.resolve()
    if not p.is_file() or _ignored(p):
        return None
    return p


def _safe_write(relpath: str) -> Path | None:
    """Путь, куда РАЗРЕШЕНО писать: внутри корня и не секрет/бинарник. Файла может
    ещё не быть (create), поэтому is_file НЕ требуем — но игнор-маску проверяем."""
    p = (ROOT / relpath)
    if not _inside_root(p):
        return None
    p = p.resolve()
    if _ignored(p) or p.is_dir():
        return None
    return p


def _walk() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in config.IGNORE_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if not _ignored(p):
                out.append(p)
    return out


# ═══════════════════════ ЧТЕНИЕ (System Tools, §8) ═══════════════════════
def list_files(subdir: str = ".", limit: int = 200) -> dict:
    """Карта проекта: относительные пути всех текстовых файлов (subdir — сузить)."""
    root = (ROOT / subdir)
    if not _inside_root(root):
        return {"error": "путь вне проекта"}
    root = root.resolve()
    files = sorted(str(p.relative_to(ROOT)) for p in _walk() if str(p).startswith(str(root)))
    return {"count": len(files), "files": files[:limit], "truncated": len(files) > limit}


def grep_repo(pattern: str, glob: str = "*", max_hits: int = MAX_GREP_HITS) -> dict:
    """Точный поиск строки/регэкспа по файлам проекта. Возвращает {file,line,text}."""
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
                hits.append({"file": str(p.relative_to(ROOT)), "line": i,
                             "text": line.strip()[:200]})
                if len(hits) >= max_hits:
                    return {"pattern": pattern, "scanned_files": scanned,
                            "hits": hits, "truncated": True}
    return {"pattern": pattern, "scanned_files": scanned, "hits": hits, "truncated": False}


def read_file(relpath: str, max_bytes: int = MAX_READ_BYTES) -> dict:
    """Прочитать текстовый файл проекта (в клетке §11). Крупный — обрезаем."""
    p = _safe_read(relpath)
    if p is None:
        return {"error": f"нельзя прочитать '{relpath}' (вне проекта, секрет или не файл)"}
    data = p.read_text(encoding="utf-8", errors="ignore")
    return {"file": relpath, "truncated": len(data) > max_bytes,
            "text": data[:max_bytes], "bytes": len(data)}


# ═══════════════════════ ЗАПИСЬ: подготовка правки (не пишем!) ═══════════════════════
def _unified_diff(relpath: str, old: str, new: str) -> str:
    """Собрать unified diff ‘было → стало’ ДЛЯ ПОКАЗА человеку. Генерит наш код,
    а не модель (бриф: diff читать человеку удобно, но модели генерить хрупко)."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{relpath}", tofile=f"b/{relpath}", lineterm="")
    return "\n".join(lines)


def propose_edit(relpath: str, old_str: str, new_str: str) -> dict:
    """Подготовить точечную правку файла (search/replace). НЕ пишет на диск.

    Контракт как у str_replace Anthropic: old_str обязан совпасть ДОСЛОВНО и РОВНО
    ОДИН раз. 0 совпадений или несколько — правка отклоняется с понятной ошибкой,
    чтобы модель прислала более точный/контекстный фрагмент."""
    p = _safe_write(relpath)
    if p is None or not p.is_file():
        return {"error": f"нельзя изменить '{relpath}' (вне проекта, секрет, или файла нет — для нового используй propose_create)"}
    text = p.read_text(encoding="utf-8", errors="ignore")
    cnt = text.count(old_str)
    if cnt == 0:
        return {"error": "old_str не найден ДОСЛОВНО. Пришли точный фрагмент с теми же отступами/пробелами."}
    if cnt > 1:
        return {"error": f"old_str встречается {cnt} раз — неоднозначно. Добавь окружающий контекст, чтобы совпадение было ровно одно."}
    new_text = text.replace(old_str, new_str, 1)
    if new_text == text:
        return {"error": "правка ничего не меняет (old_str == new_str)."}
    return {"ok": True, "kind": "edit", "relpath": relpath, "new_text": new_text,
            "diff": _unified_diff(relpath, text, new_text)}


def propose_create(relpath: str, content: str) -> dict:
    """Подготовить создание нового файла (отчёт/README/ADR/changelog). НЕ пишет."""
    p = _safe_write(relpath)
    if p is None:
        return {"error": f"нельзя создать '{relpath}' (вне проекта или запрещённое имя)"}
    if p.is_file():
        return {"error": f"файл '{relpath}' уже есть — используй propose_edit для изменения."}
    return {"ok": True, "kind": "create", "relpath": relpath, "new_text": content,
            "diff": _unified_diff(relpath, "", content)}


# ═══════════════════════ ЗАПИСЬ: применение по подтверждению (§11/§14) ═══════════════════════
def apply_change(relpath: str, new_text: str) -> dict:
    """Реально записать подготовленную правку — АТОМАРНО (temp + os.replace, приём
    Дня 7). Вызывается ТОЛЬКО после подтверждения человеком в UI. Клетку проверяем
    ещё раз здесь — apply не доверяет тому, кто его позвал."""
    p = _safe_write(relpath)
    if p is None:
        return {"error": f"запись в '{relpath}' запрещена клеткой §11"}
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp_", suffix=p.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, p)                    # атомарная подмена: обрыв не оставит огрызок
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)                    # убрать temp при сбое
        return {"error": f"не удалось записать: {type(e).__name__}: {e}"}
    return {"applied": True, "relpath": relpath, "bytes": len(new_text.encode("utf-8"))}


if __name__ == "__main__":
    print("list_files:", list_files()["files"])
    print("\ngrep save_note:", [(h["file"], h["line"]) for h in grep_repo(r"save_note")["hits"]])
    # propose (не пишет)
    pe = propose_edit("docs/api.md", "## `save_note(text)`", "## `save_note(text, tags=None)`")
    print("\npropose_edit ok?", pe.get("ok"), "\n--- diff ---\n", pe.get("diff") or pe.get("error"))
    # jail-тесты записи
    print("\njail write .env:", propose_create("../.env", "x").get("error"))
    print("jail write outside:", propose_create("../../secret.txt", "x").get("error"))

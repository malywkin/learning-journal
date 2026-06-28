"""
День 20 — СЕРВЕР №2 «storage». Вторая стойка. Учебный двойник официального сервера
`filesystem`.

Что умеет:
  • save_note(title, content) — сохранить заметку в файл (ЕДИНСТВЕННЫЙ инструмент, который ПИШЕТ);
  • read_note(filename)       — прочитать заметку;
  • list_notes()             — перечислить, что уже сохранено.

Куда «подключается»: на ЛОКАЛЬНЫЙ ДИСК (папка notes/ внутри дня) — не в интернет. Это пример
сервера, который наружу не ходит вообще: «шкаф с папками» прямо за стойкой.

Слушает 127.0.0.1:8102, Streamable HTTP.
"""

import os
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

HERE = Path(__file__).parent
NOTES_DIR = HERE / "notes"  # «шкаф с папками» этого сервера


class SaveResult(BaseModel):
    ok: bool
    filename: str = ""
    path: str = ""
    bytes: int = 0
    error: str = ""


class ReadResult(BaseModel):
    ok: bool
    filename: str = ""
    content: str = ""
    error: str = ""


class ListResult(BaseModel):
    ok: bool
    count: int = 0
    notes: list[str] = Field(default_factory=list)
    error: str = ""


mcp = FastMCP("storage", host="127.0.0.1", port=8102)


def _safe_name(name: str) -> str:
    """Обезвредить имя файла: только буквы/цифры/._-, не дать вылезти из папки notes/."""
    base = os.path.basename((name or "").strip())
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base) or "note"
    if not base.endswith((".md", ".txt")):
        base += ".md"
    return base


@mcp.tool(annotations=ToolAnnotations(title="Сохранить заметку", readOnlyHint=False))
def save_note(title: str, content: str) -> SaveResult:
    """Сохранить готовый текст в файл-заметку. Это финал флоу: сюда кладут переведённую
    сводку вместе с отметкой времени. Пишет на диск → readOnlyHint=False."""
    if not content or not content.strip():
        return SaveResult(ok=False, error="пустой контент: нечего сохранять")
    NOTES_DIR.mkdir(exist_ok=True)
    fname = _safe_name(title or f"note_{int(time.time())}")
    path = NOTES_DIR / fname
    data = content.strip() + "\n"
    path.write_text(data, encoding="utf-8")
    return SaveResult(ok=True, filename=fname, path=str(path), bytes=len(data.encode("utf-8")))


@mcp.tool(annotations=ToolAnnotations(title="Прочитать заметку", readOnlyHint=True))
def read_note(filename: str) -> ReadResult:
    """Прочитать ранее сохранённую заметку по имени файла (только из папки notes/)."""
    fname = _safe_name(filename)
    path = NOTES_DIR / fname
    if not path.exists():
        return ReadResult(ok=False, filename=fname, error="файл не найден")
    return ReadResult(ok=True, filename=fname, content=path.read_text(encoding="utf-8"))


@mcp.tool(annotations=ToolAnnotations(title="Список заметок", readOnlyHint=True))
def list_notes() -> ListResult:
    """Перечислить все сохранённые заметки в папке notes/."""
    if not NOTES_DIR.exists():
        return ListResult(ok=True, count=0, notes=[])
    names = sorted(p.name for p in NOTES_DIR.glob("*") if p.is_file())
    return ListResult(ok=True, count=len(names), notes=names)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

"""
День 31 — инструмент №2 роутера: MCP-git-сервер (живое состояние репозитория).

Переиспользуем каркас Дня 17 (day17/mcp_server.py): FastMCP, @mcp.tool на обычной
функции, ToolAnnotations. Отличия под задание Дня 31:
  - транспорт stdio, а не streamable-http: приложение поднимет сервер как под-процесс
    без портов (проще упаковать в продукт);
  - ВСЕ инструменты read-only (git branch/status/diff/log) — размечены readOnlyHint=True.
    Это ровно §11 конспекта (безопасные vs опасные операции): читать состояние — безопасно,
    менять (commit/checkout/push) — сюда НЕ кладём вовсе (белый список подкоманд ниже).
  - возвращаем Pydantic-модели, чтобы у ответа был structuredContent, а не только текст
    (память fastmcp-dict-no-structuredcontent: голый dict его не даёт).

Бриф (18.07): официальный референс-git-сервер MCP размечает эти же инструменты
readOnlyHint=true. Оговорка спеки: аннотация — ХИНТ, не гарантия; поэтому безопасность
держим НЕ на хинте, а на белом списке read-only подкоманд в _git() ниже.
"""
import subprocess

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import config

# Белый список: только читающие подкоманды git. Всё остальное (commit/checkout/push/
# reset/clean/rm) сюда не попадёт — это и есть sandbox §11 «опасное не пускаем».
_ALLOWED = {"branch", "status", "diff", "log", "show", "rev-parse"}

mcp = FastMCP("git-day31")


def _git(*args: str) -> str:
    """Выполнить читающую git-команду в config.REPO_ROOT. Опасные подкоманды режем."""
    if not args or args[0] not in _ALLOWED:
        raise ValueError(f"подкоманда git '{args[0] if args else ''}' не разрешена (только чтение)")
    try:
        r = subprocess.run(["git", "-C", str(config.REPO_ROOT), *args],
                           capture_output=True, text=True, timeout=15)
    except Exception as e:
        return f"(ошибка запуска git: {type(e).__name__})"
    return (r.stdout or r.stderr or "").strip()


# ── Модели результата (structuredContent, фишка спецификации) ──
class BranchInfo(BaseModel):
    current: str
    all_branches: list[str]


class TextResult(BaseModel):
    text: str


_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)   # безопасно + локально


@mcp.tool(annotations=_RO)
def git_branch() -> BranchInfo:
    """Текущая git-ветка проекта и список всех веток. Только читает."""
    current = _git("rev-parse", "--abbrev-ref", "HEAD")
    raw = _git("branch", "--format=%(refname:short)")
    branches = [b.strip() for b in raw.splitlines() if b.strip()]
    return BranchInfo(current=current, all_branches=branches)


@mcp.tool(annotations=_RO)
def git_status() -> TextResult:
    """Состояние рабочего дерева: изменённые/новые/staged файлы (git status). Только читает."""
    return TextResult(text=_git("status", "--short", "--branch") or "(рабочее дерево чистое)")


@mcp.tool(annotations=_RO)
def git_log(n: int = 5) -> TextResult:
    """Последние n коммитов: хеш, дата, автор, сообщение (git log). Только читает."""
    n = max(1, min(int(n), 30))
    return TextResult(text=_git("log", f"-{n}", "--pretty=format:%h %ad %an: %s", "--date=short"))


@mcp.tool(annotations=_RO)
def git_diff(staged: bool = False) -> TextResult:
    """Незакоммиченные изменения (git diff). staged=True — уже добавленные в индекс. Читает."""
    args = ["diff", "--stat"] + (["--staged"] if staged else [])
    out = _git(*args)
    return TextResult(text=out or "(изменений нет)")


if __name__ == "__main__":
    mcp.run(transport="stdio")

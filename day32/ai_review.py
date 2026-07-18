"""
День 32 — AI-ревьюер кода. Ядро пайплайна из §13 конспекта:

    PR открыт → берём diff → достаём правила и код проекта (RAG) → модель пишет ревью
    → кладём комментарием в PR.

Мозг переиспользован с Дня 31 (тот же openai-SDK, провайдер-развязка). Новое —
только концы трубы: вход берём из diff PR, выход кладём комментарием в PR.

Два режима:
  • локальный (`--diff файл`)  — печатает ревью в консоль (наш smoke test, §16);
  • CI (`--pr N`)              — берёт diff через `gh pr diff N`, постит комментарий.

Всё завёрнуто в §14: модель ненадёжна, поэтому её сбой НЕ роняет job и НЕ мешает
влить PR. Ревью — рекомендация, не запрет (никогда не выходим с ненулевым кодом).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

import config
import review_llm

MARKER = "<!-- ai-review-bot -->"   # метка своего комментария (чтобы править, а не плодить)


# ────────────────────────── вход: получить diff ──────────────────────────
def diff_via_gh(pr: str) -> str:
    """CI-путь A из брифа (рекомендованный): gh предустановлен на раннере."""
    out = subprocess.run(["gh", "pr", "diff", pr, "--patch"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"gh pr diff упал: {out.stderr.strip()}")
    return out.stdout


def read_diff(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return open(path, encoding="utf-8", errors="replace").read()


# ──────────────────── контекст (RAG, лёгкий путь для CI) ────────────────────
def changed_files(diff: str) -> list[str]:
    """Пути изменённых файлов из unified diff (строки '+++ b/путь')."""
    files = []
    for line in diff.splitlines():
        m = re.match(r"\+\+\+ b/(.+)", line)
        if m and m.group(1) != "/dev/null":
            files.append(m.group(1).strip())
    return files


def gather_context(files: list[str]) -> str:
    """Достаём правила проекта + доки/код рядом с правкой — как в сценке про брендбук.

    Это и есть RAG «документация + код» из задания, только лёгким путём под CI:
    вместо тяжёлого векторного поиска (Дни 21-24, torch) — берём релевантные доки
    по пути изменённого файла. Быстро, дёшево, без модели-эмбеддера на раннере.
    """
    parts = []

    # 1) «брендбук» — правила проекта, всегда
    if config.REVIEW_GUIDE.exists():
        parts.append("### Правила проекта (REVIEW_GUIDE.md)\n"
                     + config.REVIEW_GUIDE.read_text(encoding="utf-8"))

    # 2) доки дня, к которому относится правка (day07/memory.py → day07/takeaways.md ...)
    seen = set()
    for f in files:
        day = f.split("/")[0]                       # 'day07/...' → 'day07'
        for suffix in config.DOC_SUFFIXES:
            doc = config.REPO_ROOT / day / suffix
            if doc.exists() and doc not in seen:
                seen.add(doc)
                parts.append(f"### {day}/{suffix}\n"
                             + doc.read_text(encoding="utf-8")[:3000])

    # 3) немного кода рядом: текущее содержимое изменённых файлов (обрезанное)
    budget = config.MAX_CODE_CHARS
    for f in files:
        if any(part in config.IGNORE_PATH_PARTS for part in f.split("/")):
            continue
        p = config.REPO_ROOT / f
        if p.exists() and p.is_file() and budget > 0:
            body = p.read_text(encoding="utf-8", errors="replace")[:budget]
            budget -= len(body)
            parts.append(f"### Текущий код {f}\n```\n{body}\n```")

    return "\n\n".join(parts) if parts else "(доп. контекст не найден)"


# ────────────────────────── промпт и разбор ──────────────────────────
SYSTEM = """Ты — внимательный ревьюер кода в проекте learning-journal (учебный курс по ИИ, Python).
Тебе дают PR: сам diff (что изменилось) и контекст — правила проекта и код рядом.
Отвечай ПО-РУССКИ. Смотри ТОЛЬКО на изменения из diff, сверяя их с правилами проекта.
Ты советуешь, а не запрещаешь: тон — рекомендательный, финальное слово за человеком.
Не придирайся к стилю, если он не меняет смысл. Если правка хорошая — так и скажи.

Верни СТРОГО один JSON-объект по шаблону (без текста вокруг):
{
  "verdict": "approve" | "comment" | "request_changes",
  "summary": "1-2 предложения: главное о PR",
  "bugs": ["потенциальные баги — каждый пункт кратко, с файлом/строкой если ясно"],
  "architecture": ["архитектурные проблемы"],
  "recommendations": ["рекомендации по улучшению"]
}
Пустые списки — это нормально. Не выдумывай проблемы, если их нет."""


def build_user(diff: str, context: str) -> str:
    diff = diff[:config.MAX_DIFF_CHARS]
    return f"# Контекст проекта\n{context}\n\n# Diff этого PR\n```diff\n{diff}\n```"


def to_markdown(rv: dict, provider: str) -> str:
    """Собрать человекочитаемое ревью для комментария в PR."""
    verdict = {"approve": "можно мержить",
               "comment": "есть замечания",
               "request_changes": "нужны правки"}.get(rv.get("verdict"), "есть замечания")
    lines = [MARKER, "## AI-ревью", "", f"**Вердикт:** {verdict}", "",
             rv.get("summary", "").strip(), ""]

    def block(title, items):
        items = [i for i in (items or []) if str(i).strip()]
        if items:
            lines.append(f"**{title}**")
            lines.extend(f"- {i}" for i in items)
            lines.append("")

    block("Потенциальные баги", rv.get("bugs"))
    block("Архитектурные проблемы", rv.get("architecture"))
    block("Рекомендации", rv.get("recommendations"))
    lines.append(f"<sub>Это рекомендация, не запрет на мерж. Проверил: {provider}.</sub>")
    return "\n".join(lines)


# ────────────────────────── выход: комментарий в PR ──────────────────────────
def _gh_json(args: list[str]):
    import json
    out = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout or "null")


def post_comment(pr: str, body: str, repo: str) -> None:
    """Кладём/обновляем один комментарий (против спама на каждый push — правим свой)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        body_file = fh.name

    # ищем свой прошлый комментарий по метке → редактируем, иначе создаём новый
    try:
        comments = _gh_json(["gh", "api", f"repos/{repo}/issues/{pr}/comments",
                             "--paginate"]) or []
        mine = next((c for c in comments if MARKER in (c.get("body") or "")), None)
        if mine:
            subprocess.run(["gh", "api", "--method", "PATCH",
                            f"repos/{repo}/issues/comments/{mine['id']}",
                            "-F", f"body=@{body_file}"], check=True, timeout=60)
            print("[out] обновил существующий комментарий", flush=True)
            return
    except Exception as e:
        print(f"[out] не смог проверить старые комментарии: {type(e).__name__}", flush=True)

    subprocess.run(["gh", "pr", "comment", pr, "--body-file", body_file],
                   check=True, timeout=60)
    print("[out] оставил новый комментарий", flush=True)


# ────────────────────────── сборка пайплайна ──────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="AI-ревьюер кода (День 32)")
    ap.add_argument("--pr", help="номер PR (CI-режим: берём diff через gh, постим коммент)")
    ap.add_argument("--diff", help="файл с diff или '-' для stdin (локальный режим: печать)")
    ap.add_argument("--repo", default=os.getenv("GH_REPO", ""), help="owner/repo для API")
    args = ap.parse_args()

    # 1) вход — diff
    try:
        diff = diff_via_gh(args.pr) if args.pr and not args.diff else read_diff(args.diff or "-")
    except Exception as e:
        print(f"[!] не смог получить diff: {e}", flush=True)
        return 0                                   # §14: не роняем job

    if not diff.strip():
        print("[i] пустой diff — нечего ревьюить", flush=True)
        return 0

    files = changed_files(diff)
    print(f"[i] изменённых файлов: {len(files)} → {files}", flush=True)

    # 2) контекст (RAG) + 3) запрос к модели (retry→fallback внутри)
    context = gather_context(files)
    review, provider = review_llm.ask_json(SYSTEM, build_user(diff, context))

    if review is None:
        print("[!] модель недоступна после всех попыток — ревью не создано", flush=True)
        return 0                                   # §14: тихо выходим, PR не блокируем

    body = to_markdown(review, provider)

    # 4) выход
    if args.pr:
        try:
            post_comment(args.pr, body, args.repo)
        except Exception as e:
            print(f"[!] не смог запостить комментарий: {e}", flush=True)
        return 0
    else:
        print("\n" + "=" * 70 + "\n" + body + "\n" + "=" * 70, flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())

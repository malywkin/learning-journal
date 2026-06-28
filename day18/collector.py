"""
День 18 — слой данных и «работа», которую планировщик запускает по часам.

Здесь нет ни планировщика, ни MCP — только три вещи, понятные сами по себе:
  • collect_subreddit(...) — СБОР: сходить в Reddit (через твой arctic), взять свежие
    посты, дозаписать в SQLite только НОВЫЕ (по id, без дублей). Это «периодический сбор».
  • make_digest(...)       — СВОДКА: взять накопленные посты и свернуть их LLM в короткий
    дайджест «что нового». Это «регулярный summary». Результат тоже кладём в SQLite.
  • reminder(...)          — НАПОМИНАНИЕ: разовое отложенное событие (просто пишем в журнал).

Функции — НА УРОВНЕ МОДУЛЯ и с простыми аргументами (строки/числа). Это важно: планировщик
(scheduler.py) хранит задачи на диске и ссылается на функцию по имени «collector:collect_subreddit».
Замыкание или метод так сохранить нельзя — поэтому всё плоско и импортируемо.

Каждая функция-«работа» сама открывает своё подключение к SQLite: задачи планировщик гоняет
в пуле потоков, а одно sqlite-соединение между потоками шарить нельзя.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

import arctic  # вендорная копия твоего reddit-клиента (Arctic Shift, без ключей)

load_dotenv()

HERE = Path(__file__).parent
DB_PATH = str(HERE / "day18.db")

# Модель для сводки. 120b ровнее держит формат; вызову даём таймаут и temp 0.
SUMMARY_MODEL = "openai/gpt-oss-120b:free"


# ---------- хранилище ----------

def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Создать таблицы при первом запуске. Идемпотентно (IF NOT EXISTS)."""
    with _conn(db_path) as c:
        # WAL — чтобы веб-витрина читала базу, пока фоновые задачи в неё пишут (без блокировок).
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id            TEXT PRIMARY KEY,   -- id поста: гарантия «без дублей»
                subreddit     TEXT,
                title         TEXT,
                author        TEXT,
                score         INTEGER,
                num_comments  INTEGER,
                created_utc   INTEGER,
                permalink     TEXT,
                fetched_at    REAL                -- когда МЫ его подобрали
            );
            CREATE TABLE IF NOT EXISTS digests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                subreddit   TEXT,
                created_at  REAL,
                n_posts     INTEGER,
                summary     TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL,      -- когда сработала задача
                kind       TEXT,      -- collect | digest | reminder
                subreddit  TEXT,
                detail     TEXT       -- человекочитаемый итог тика
            );
            """
        )


def _log_run(kind: str, subreddit: str, detail: str, db_path: str = DB_PATH) -> None:
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO runs (ts, kind, subreddit, detail) VALUES (?,?,?,?)",
            (time.time(), kind, subreddit, detail),
        )


def _trim(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "subreddit": p.get("subreddit"),
        "title": p.get("title"),
        "author": p.get("author"),
        "score": p.get("score") or 0,
        "num_comments": p.get("num_comments") or 0,
        "created_utc": p.get("created_utc") or 0,
        "permalink": p.get("permalink"),
    }


# ---------- РАБОТА №1: периодический сбор ----------

def collect_subreddit(subreddit: str, limit: int = 25, db_path: str = DB_PATH) -> dict:
    """Сходить за свежими постами и дозаписать только НОВЫЕ. Возвращает агрегат тика.

    Это и есть «задача по расписанию»: планировщик зовёт её каждые N минут.
    Дубли отсекаются на уровне БД (INSERT OR IGNORE по первичному ключу id) — поэтому
    повторный запуск на тех же данных ничего не ломает (идемпотентность по строке).
    """
    init_db(db_path)
    try:
        posts = arctic.search_posts(subreddit=subreddit, sort="desc", limit=limit)
    except Exception as e:  # чужой архив может тормозить/лежать — не роняем тик
        _log_run("collect", subreddit, f"ошибка сбора: {type(e).__name__}: {e}", db_path)
        return {"ok": False, "error": str(e), "new": 0}

    now = time.time()
    new = 0
    with _conn(db_path) as c:
        for raw in posts:
            t = _trim(raw)
            if not t["id"]:
                continue
            cur = c.execute(
                """INSERT OR IGNORE INTO posts
                   (id, subreddit, title, author, score, num_comments, created_utc, permalink, fetched_at)
                   VALUES (:id,:subreddit,:title,:author,:score,:num_comments,:created_utc,:permalink,:fetched_at)""",
                {**t, "fetched_at": now},
            )
            new += cur.rowcount  # 1 если строка реально вставилась, 0 если уже была
        total = c.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE subreddit = ?", (subreddit,)
        ).fetchone()["n"]

    _log_run("collect", subreddit, f"подобрано новых: {new} (всего в базе: {total})", db_path)
    return {"ok": True, "new": new, "total": total}


# ---------- РАБОТА №2: регулярная сводка ----------

def _llm() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=90,
    )


def make_digest(subreddit: str, take: int = 15, db_path: str = DB_PATH) -> dict:
    """Свернуть последние посты в короткий дайджест «что нового». Кладём в SQLite.

    Ограничитель против выдумок (как в Днях 9–12): запрещаем придумывать, temp 0,
    короткий потолок — слабая free-модель иначе фантазирует на бедном входе.
    """
    init_db(db_path)
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT title, score, num_comments FROM posts WHERE subreddit = ? "
            "ORDER BY created_utc DESC LIMIT ?",
            (subreddit, take),
        ).fetchall()

    if not rows:
        _log_run("digest", subreddit, "нет постов для сводки", db_path)
        return {"ok": False, "error": "нет данных", "summary": ""}

    titles = "\n".join(f"- {r['title']} (score {r['score']}, {r['num_comments']} комм.)" for r in rows)
    system = (
        "Ты делаешь короткий дайджест по заголовкам постов Reddit. Пиши по-русски, "
        "3–5 пунктов, только по тому, что есть в списке. НИЧЕГО не придумывай: не добавляй "
        "фактов, имён и цифр, которых нет во входе. Без вступлений и воды."
    )
    try:
        resp = _llm().chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Посты из r/{subreddit}:\n{titles}\n\nСделай дайджест «что нового»."},
            ],
            temperature=0,
            max_tokens=450,
            extra_body={"reasoning": {"effort": "low"}},
        )
        summary = (resp.choices[0].message.content or "").strip()
    except APIStatusError as e:
        _log_run("digest", subreddit, f"ошибка LLM: {e.status_code}", db_path)
        return {"ok": False, "error": f"LLM {e.status_code}", "summary": ""}

    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO digests (subreddit, created_at, n_posts, summary) VALUES (?,?,?,?)",
            (subreddit, time.time(), len(rows), summary),
        )
    _log_run("digest", subreddit, f"сводка готова по {len(rows)} постам", db_path)
    return {"ok": True, "n_posts": len(rows), "summary": summary}


# ---------- РАБОТА №3: разовое ОТЛОЖЕННОЕ дело (один раз через N минут) ----------

def collect_and_digest(subreddit: str, db_path: str = DB_PATH) -> dict:
    """Разовое отложенное дело: ОДИН раз собрать свежие посты и сразу свернуть в сводку.
    Планировщик запускает это один раз в назначенный срок (триггер 'date')."""
    c = collect_subreddit(subreddit, db_path=db_path)
    d = make_digest(subreddit, db_path=db_path)
    _log_run("oneshot", subreddit,
             f"разовое дело выполнено: собрано {c.get('new', 0)}, сводка {'готова' if d.get('ok') else 'не вышла'}",
             db_path)
    return {"ok": True, "collected": c.get("new"), "digest_ok": d.get("ok")}


# ---------- чтение для CLI/витрины (агрегаты «забрать», pull) ----------

def latest_digest(subreddit: str, db_path: str = DB_PATH) -> dict | None:
    with _conn(db_path) as c:
        r = c.execute(
            "SELECT subreddit, created_at, n_posts, summary FROM digests "
            "WHERE subreddit = ? ORDER BY id DESC LIMIT 1",
            (subreddit,),
        ).fetchone()
    return dict(r) if r else None


def recent_runs(limit: int = 12, db_path: str = DB_PATH) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT ts, kind, subreddit, detail FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def status(subreddit: str, db_path: str = DB_PATH) -> dict:
    init_db(db_path)
    with _conn(db_path) as c:
        n_posts = c.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE subreddit = ?", (subreddit,)
        ).fetchone()["n"]
        n_digests = c.execute(
            "SELECT COUNT(*) AS n FROM digests WHERE subreddit = ?", (subreddit,)
        ).fetchone()["n"]
    return {
        "subreddit": subreddit,
        "posts": n_posts,
        "digests": n_digests,
        "latest_digest": latest_digest(subreddit, db_path),
        "recent_runs": recent_runs(12, db_path),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

"""
День 18 — НАШ MCP-сервер с фоновым планировщиком внутри.

Связь с Днём 17: там инструмент срабатывал только когда к нему обратятся (реактивный
официант). Здесь рядом, в ТОМ ЖЕ процессе, живёт планировщик (повар с будильником) —
он сам по часам собирает посты и пишет сводку, кладёт всё в SQLite.

Главный приём дня видно в инструментах:
  • schedule_collection / schedule_digest / add_reminder — РЕГИСТРИРУЮТ задачу в
    планировщике и СРАЗУ возвращают ответ. Инструмент НЕ спит до срабатывания
    (иначе заблокировал бы сервер — антипаттерн №1 из брифа).
  • get_digest / get_status — ЗАБРАТЬ накопленный агрегат (pull). Сервер не «будит»
    клиента — клиент сам приходит за результатом. Это надёжный контракт (бриф: pull > push).

Планировщик стартует в lifespan сервера и хранит расписание на диске → задачи переживают
перезапуск. Транспорт — Streamable HTTP, слушаем только 127.0.0.1 (как в Дне 17).
Запуск:  python mcp_server.py
"""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import collector
import scheduler as sch

# Планировщик один на процесс. Стартуем его в lifespan (там есть живой event loop).
_scheduler = None


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Поднять планировщик при старте сервера, погасить при остановке."""
    global _scheduler
    collector.init_db()
    _scheduler = sch.build_scheduler()
    _scheduler.start()  # с диска поднимутся ранее заведённые задачи → переживают рестарт
    try:
        yield {}
    finally:
        _scheduler.shutdown(wait=False)


mcp = FastMCP("reddit-scheduler-day18", host="127.0.0.1", port=8018, lifespan=lifespan)


# ---------- инструменты, которые СТАВЯТ задачу на расписание (и сразу возвращаются) ----------

@mcp.tool(annotations=ToolAnnotations(title="Запланировать сбор постов", readOnlyHint=False))
def schedule_collection(subreddit: str, every_minutes: int = 10) -> dict:
    """Каждые every_minutes минут собирать свежие посты из r/<subreddit> в базу.
    Первый сбор — сразу. Инструмент только регистрирует задачу и возвращает её id."""
    job_id = sch.add_collection_job(_scheduler, subreddit, every_minutes)
    return {"scheduled": job_id, "subreddit": subreddit, "every_minutes": every_minutes,
            "message": f"Сбор r/{subreddit} каждые {every_minutes} мин — поставлен."}


@mcp.tool(annotations=ToolAnnotations(title="Запланировать сводку", readOnlyHint=False))
def schedule_digest(subreddit: str, every_minutes: int = 15) -> dict:
    """Каждые every_minutes минут сворачивать накопленные посты r/<subreddit> в дайджест."""
    job_id = sch.add_digest_job(_scheduler, subreddit, every_minutes)
    return {"scheduled": job_id, "subreddit": subreddit, "every_minutes": every_minutes,
            "message": f"Сводка r/{subreddit} каждые {every_minutes} мин — поставлена."}


@mcp.tool(annotations=ToolAnnotations(title="Сводка по времени (cron)", readOnlyHint=False))
def schedule_daily_digest(subreddit: str, hour: int, minute: int = 0) -> dict:
    """Как в проде: сводка ПО ВРЕМЕНИ (cron) — каждый день в hour:minute."""
    job_id = sch.add_daily_digest_cron(_scheduler, subreddit, hour, minute)
    return {"scheduled": job_id, "message": f"Сводка r/{subreddit} ежедневно в {hour:02d}:{minute:02d}."}


@mcp.tool(annotations=ToolAnnotations(title="Разовое дело через N минут", readOnlyHint=False))
def schedule_once(subreddit: str, in_minutes: float = 1) -> dict:
    """Разовое ОТЛОЖЕННОЕ дело: один раз через in_minutes минут собрать свежие посты
    r/<subreddit> и сразу сделать сводку."""
    job_id = sch.add_oneshot_job(_scheduler, subreddit, in_minutes)
    return {"scheduled": job_id,
            "message": f"Через {in_minutes} мин один раз собрать+свернуть r/{subreddit}."}


# ---------- запустить задачу ПРЯМО СЕЙЧАС (для демо/видео — не ждать интервал) ----------

@mcp.tool(annotations=ToolAnnotations(title="Выполнить сейчас", readOnlyHint=False))
def run_now(subreddit: str, kind: str = "collect") -> dict:
    """Выполнить работу немедленно: kind='collect' (сбор) или 'digest' (сводка)."""
    if kind == "digest":
        return collector.make_digest(subreddit)
    return collector.collect_subreddit(subreddit)


# ---------- ЗАБРАТЬ результат и состояние (pull, только чтение) ----------

@mcp.tool(annotations=ToolAnnotations(title="Список задач", readOnlyHint=True))
def list_jobs() -> dict:
    """Что сейчас стоит в расписании (id, тип триггера, время следующего запуска)."""
    return {"jobs": sch.list_jobs(_scheduler)}


@mcp.tool(annotations=ToolAnnotations(title="Забрать сводку", readOnlyHint=True))
def get_digest(subreddit: str) -> dict:
    """Последний готовый дайджест по r/<subreddit> (агрегат забирают вызовом — pull)."""
    d = collector.latest_digest(subreddit)
    return d or {"message": "Сводки ещё нет — сбор/сводка не отрабатывали."}


@mcp.tool(annotations=ToolAnnotations(title="Состояние", readOnlyHint=True))
def get_status(subreddit: str) -> dict:
    """Сводное состояние: сколько постов собрано, сколько сводок, последние тики."""
    return collector.status(subreddit)


@mcp.tool(annotations=ToolAnnotations(title="Отменить задачу", readOnlyHint=False))
def cancel_job(job_id: str) -> dict:
    """Снять задачу с расписания по её id."""
    try:
        _scheduler.remove_job(job_id)
        return {"cancelled": job_id}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

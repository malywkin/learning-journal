"""
День 18 — ПЛАНИРОВЩИК (тот самый «повар с будильником» рядом с реактивным сервером).

Берём APScheduler 3.11 (стабильная ветка; 4.0 ещё alpha, «не для прода» — см. бриф).
Три вещи, ради которых он, а не самописный `while True`:

  1. РАСПИСАНИЕ НА ДИСКЕ (SQLAlchemyJobStore → отдельный sqlite-файл). Поэтому задачи
     переживают перезапуск процесса: упал/перезапустили — планировщик поднимает их с диска.
  2. БЕЗ ДУБЛЕЙ при перезапуске: у каждой задачи явный id + replace_existing=True.
     Иначе каждый старт плодил бы копию той же задачи.
  3. БЕЗ ЛАВИНЫ пропусков: coalesce=True (пропущенные за простой тики схлопываются в один),
     misfire_grace_time (окно прощения опоздания), max_instances=1 (не запускать внахлёст).

Триггеры: 'interval' — «каждые N минут» (для демо видно сразу); 'cron' — «по времени»
(в полдень по будням — как в проде); 'date' — разовое отложенное (напоминание).

AsyncIOScheduler крутится на ТОМ ЖЕ событийном цикле, что и сервер. Сами задачи —
обычные (синхронные) функции из collector.py; APScheduler гоняет их в пуле потоков,
поэтому сетевой поход в Reddit не морозит сервер (см. бриф: не блокировать event loop).
"""

from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import collector

HERE = Path(__file__).parent
# Отдельный файл под расписание — чтобы записи планировщика не толкались с нашими данными.
JOBSTORE_URL = f"sqlite:///{HERE / 'day18_jobs.sqlite'}"


def build_scheduler() -> AsyncIOScheduler:
    """Собрать планировщик с диск-хранилищем и здравыми защитами по умолчанию."""
    return AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=JOBSTORE_URL)},
        job_defaults={
            "coalesce": True,          # пропуски за простой → один запуск, не лавина
            "max_instances": 1,        # не запускать ту же задачу внахлёст
            "misfire_grace_time": 300, # опоздание до 5 минут ещё считается валидным
        },
    )


# ---------- добавление задач (каждую зовёт MCP-инструмент) ----------

def add_collection_job(sched: AsyncIOScheduler, subreddit: str, minutes: int) -> str:
    """Периодический сбор: каждые `minutes` минут собирать свежие посты subreddit."""
    job_id = f"collect:{subreddit}"
    sched.add_job(
        collector.collect_subreddit, trigger="interval", minutes=minutes,
        args=[subreddit], id=job_id, replace_existing=True,
        next_run_time=datetime.now(),  # первый сбор сразу, не ждать первый интервал
    )
    return job_id


def add_digest_job(sched: AsyncIOScheduler, subreddit: str, minutes: int) -> str:
    """Регулярная сводка: каждые `minutes` минут сворачивать накопленное в дайджест."""
    job_id = f"digest:{subreddit}"
    sched.add_job(
        collector.make_digest, trigger="interval", minutes=minutes,
        args=[subreddit], id=job_id, replace_existing=True,
    )
    return job_id


def add_daily_digest_cron(sched: AsyncIOScheduler, subreddit: str, hour: int, minute: int = 0) -> str:
    """Как в проде: сводка ПО ВРЕМЕНИ (cron), напр. каждый день в hour:minute."""
    job_id = f"digest-cron:{subreddit}"
    sched.add_job(
        collector.make_digest, trigger="cron", hour=hour, minute=minute,
        args=[subreddit], id=job_id, replace_existing=True,
    )
    return job_id


def add_oneshot_job(sched: AsyncIOScheduler, subreddit: str, in_minutes: float) -> str:
    """Разовое ОТЛОЖЕННОЕ дело: один раз через in_minutes минут собрать и свернуть в сводку."""
    run_at = datetime.now() + timedelta(minutes=in_minutes)
    job_id = f"oneshot:{int(run_at.timestamp())}"
    sched.add_job(
        collector.collect_and_digest, trigger="date", run_date=run_at,
        args=[subreddit], id=job_id, replace_existing=True,
    )
    return job_id


# ---------- чтение состояния расписания ----------

def _trigger_str(job) -> str:
    return str(job.trigger)


def list_jobs(sched: AsyncIOScheduler) -> list[dict]:
    out = []
    for job in sched.get_jobs():
        nxt = job.next_run_time
        out.append({
            "id": job.id,
            "name": job.func_ref.split(":")[-1] if hasattr(job, "func_ref") else job.id,
            "trigger": _trigger_str(job),
            "next_run": nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None,
            "args": list(job.args),
        })
    return out

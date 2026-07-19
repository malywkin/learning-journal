"""
День 35 — ПЛАНИРОВЩИК (это TRIGGER пайплайна по §12). Реюз Дня 18, ничего с нуля.

Тот же APScheduler с расписанием НА ДИСКЕ (SQLAlchemyJobStore), что и в Дне 18 — поэтому
задача «раз в неделю собрать дайджест» переживает перезапуск и выключение компьютера:
подняли процесс — планировщик читает расписание с диска и знает, когда следующий запуск.

Три защиты по умолчанию — те же, что объясняли в Дне 18:
  • coalesce=True     — пропущенные за простой недели схлопываются в один запуск, не лавиной;
  • max_instances=1   — не запускать сборку внахлёст;
  • misfire_grace_time — опоздание (спал компьютер) до окна прощения ещё считается валидным.

Триггер 'cron' — «по времени» (раз в неделю в заданный день/час), как в проде. Для показа
на видео есть 'interval' (каждые N минут) — сразу видно, что расписание живое.
"""
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import config

JOBSTORE_URL = f"sqlite:///{config.JOBSTORE_DB}"


def build_scheduler() -> BackgroundScheduler:
    """Планировщик с диск-хранилищем и здравыми защитами (приём Дня 18)."""
    return BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=JOBSTORE_URL)},
        job_defaults={
            "coalesce": True,           # пропуски за простой → один запуск
            "max_instances": 1,         # не внахлёст
            "misfire_grace_time": 3600,  # опоздание до часа ещё валидно (компьютер спал)
        },
    )


def add_weekly_job(sched, func, day_of_week: str = "mon", hour: int = 9, minute: int = 0) -> str:
    """Как в проде: собирать и слать дайджест ПО ВРЕМЕНИ, напр. каждый понедельник в 9:00."""
    job_id = "weekly-digest"
    sched.add_job(func, trigger="cron", day_of_week=day_of_week, hour=hour, minute=minute,
                  id=job_id, replace_existing=True)
    return job_id


def add_interval_job(sched, func, minutes: int = 2) -> str:
    """Для демо: собирать дайджест каждые N минут — видно, что расписание работает."""
    job_id = "demo-digest"
    sched.add_job(func, trigger="interval", minutes=minutes, id=job_id,
                  replace_existing=True, next_run_time=datetime.now())
    return job_id


def list_jobs(sched) -> list[dict]:
    out = []
    for job in sched.get_jobs():
        nxt = job.next_run_time
        out.append({"id": job.id, "trigger": str(job.trigger),
                    "next_run": nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None})
    return out

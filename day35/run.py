"""
День 35 — точка входа: собрать весь пайплайн §12 воедино (Trigger → Input → Agent → Output).

Три режима:
  • python run.py --now      разово: собрать дайджест сейчас, сохранить на диск и отправить
                             в Telegram (если задан chat_id). Для проверки и для видео.
  • python run.py --serve    поднять ПЛАНИРОВЩИК (День 18): раз в неделю сам собирает и шлёт.
                             Процесс держится живым; расписание на диске переживает рестарт.
  • python run.py --demo     как --serve, но интервал каждые 2 минуты — видно, что расписание
                             работает, не дожидаясь понедельника.

Error handling §14 живёт внутри: сборка не падает без модели (digest даёт fallback из
источников), отправка не падает без ключей (просто предупреждает — «не полностью рабочим»
из формулировки задания).
"""
import argparse
import asyncio
import time

import bot
import config
import digest
import scheduler


def job_build_and_send() -> None:
    """Одна итерация пайплайна: собрать заметку → сохранить на диск → отправить в Telegram."""
    res = digest.build_digest()
    path = digest.save_digest(res)
    m = res["metrics"]
    print(f"[{time.strftime('%H:%M:%S')}] дайджест собран: {m['label']}, "
          f"рубрик {m['answered']}/{m['rubrics']}, цитат {m['verified_quotes']}, "
          f"провайдер {m['provider']}, {m['seconds']}с → {path.name}")
    if config.TG_TOKEN and config.TG_CHAT_ID:
        asyncio.run(bot.send_digest(res["telegram"]))
    else:
        print("     (Telegram не настроен — chat_id пуст; заметка сохранена на диск)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Родительский дайджест — пайплайн §12")
    ap.add_argument("--now", action="store_true", help="собрать и отправить один раз сейчас")
    ap.add_argument("--serve", action="store_true", help="планировщик: раз в неделю (пн 9:00)")
    ap.add_argument("--demo", action="store_true", help="планировщик каждые 2 минуты (для показа)")
    args = ap.parse_args()

    if args.now or not (args.serve or args.demo):
        job_build_and_send()
        return

    sched = scheduler.build_scheduler()
    if args.demo:
        scheduler.add_interval_job(sched, job_build_and_send, minutes=2)
    else:
        scheduler.add_weekly_job(sched, job_build_and_send, day_of_week="mon", hour=9)
    sched.start()
    print("Планировщик запущен. Расписание:")
    for j in scheduler.list_jobs(sched):
        print(f"  {j['id']}: {j['trigger']} → следующий {j['next_run']}")
    print("Ctrl+C для остановки.")
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        print("\nПланировщик остановлен (расписание сохранено на диске).")


if __name__ == "__main__":
    main()

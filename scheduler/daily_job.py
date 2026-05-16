"""
Ежедневный планировщик: запускает пайплайн анализа по расписанию.
Работает как отдельный контейнер.
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.config import settings
from app.core.pipeline import run_analysis_pipeline
from app.services.state_manager import load_preferences, load_profile


async def daily_job():
    logger.info("Daily analysis job started")
    profile = load_profile()
    prefs = load_preferences()

    if not profile:
        logger.warning("No resume loaded, skipping daily job")
        return

    try:
        report = await run_analysis_pipeline(
            profile=profile,
            prefs=prefs,
            top_n=10,
        )
        logger.info(
            f"Daily job done: {report.total_found} fetched, {len(report.top_vacancies)} ranked"
        )
    except Exception as e:
        logger.error(f"Daily job failed: {e}")


async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(
            hour=settings.daily_report_hour,
            minute=settings.daily_report_minute,
        ),
        id="daily_analysis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started. Daily job at "
        f"{settings.daily_report_hour:02d}:{settings.daily_report_minute:02d} UTC"
    )

    await daily_job()  # запуск сразу при старте

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

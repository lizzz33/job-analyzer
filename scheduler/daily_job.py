"""
Ежедневный планировщик: запускает пайплайн анализа по расписанию.
Работает как отдельный контейнер.
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.config import settings
from app.core.deps import get_state_manager
from app.core.pipeline import run_analysis_pipeline


async def daily_job():
    logger.info("Daily analysis job started")
    state = get_state_manager()
    profile = state.load_profile()
    prefs = state.load_preferences()

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
            "Daily job done: {} fetched, {} ranked",
            report.total_found,
            len(report.top_vacancies),
        )
    except Exception as e:
        logger.error("Daily job failed: {}", e)


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
        "Scheduler started. Daily job at {:02d}:{:02d} UTC",
        settings.daily_report_hour,
        settings.daily_report_minute,
    )

    await daily_job()  # запуск сразу при старте

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

"""
FastAPI backend — основной сервис.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from loguru import logger

from app.core.config import settings
from app.core.deps import get_resume_parser, get_state_manager, get_vector_store
from app.models.schemas import UserPreferences

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

_PIPELINE_COOLDOWN = 60  # seconds between pipeline runs

_pipeline_lock: asyncio.Lock | None = None
_pipeline_last_run: float = 0
_scheduler_instance = None


def _get_pipeline_lock() -> asyncio.Lock:
    global _pipeline_lock
    if _pipeline_lock is None:
        _pipeline_lock = asyncio.Lock()
    return _pipeline_lock


def _verify_api_key(request: Request) -> None:
    """API-key auth. Skip check if API_KEY is not configured."""
    if not settings.api_key:
        return
    key = request.headers.get("X-API-Key", "")
    if key != settings.api_key:
        raise HTTPException(401, "Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline_lock
    _pipeline_lock = asyncio.Lock()

    if settings.scheduler_enabled:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        from scheduler.daily_job import daily_job

        global _scheduler_instance
        _scheduler_instance = AsyncIOScheduler()
        _scheduler_instance.add_job(
            daily_job,
            trigger=CronTrigger(
                hour=settings.daily_report_hour,
                minute=settings.daily_report_minute,
            ),
            id="daily_analysis",
            replace_existing=True,
        )
        _scheduler_instance.start()
        logger.info(
            "Scheduler started — daily job at {:02d}:{:02d} UTC",
            settings.daily_report_hour,
            settings.daily_report_minute,
        )
    yield
    if _scheduler_instance:
        _scheduler_instance.shutdown()
        logger.info("Scheduler stopped")


app = FastAPI(
    title="Job Analyzer API",
    description="Ассистент по подбору вакансий",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)


@app.get("/")
def root():
    return RedirectResponse(url="/docs")


# ── Resume ────────────────────────────────────────────────────────────────────


@app.post("/resume/upload", summary="Загрузить резюме")
async def upload_resume(
    file: UploadFile = File(...),
    _auth: None = Depends(_verify_api_key),
):
    allowed = {".pdf", ".docx", ".txt"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"Поддерживаемые форматы: {allowed}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Файл слишком большой (макс. 10 МБ)")

    dest = Path(settings.resumes_path) / f"resume{suffix}"
    dest.write_bytes(content)

    try:
        parser = get_resume_parser()
        state = get_state_manager()
        profile = await parser.parse(dest)
        state.save_profile(profile)
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        logger.error("Resume parse error: {}", e)
        raise HTTPException(500, "Ошибка парсинга резюме. Проверьте формат файла.") from e


@app.get("/resume/profile")
def get_profile(_auth: None = Depends(_verify_api_key)):
    state = get_state_manager()
    profile = state.load_profile()
    if not profile:
        raise HTTPException(404, "Резюме не загружено")
    return profile.model_dump()


@app.delete("/resume/profile")
def remove_profile(_auth: None = Depends(_verify_api_key)):
    state = get_state_manager()
    state.delete_profile()
    for ext in (".pdf", ".docx", ".txt"):
        f = Path(settings.resumes_path) / f"resume{ext}"
        if f.exists():
            f.unlink()
    return {"status": "ok"}


# ── Preferences ───────────────────────────────────────────────────────────────


@app.post("/preferences")
def set_preferences(prefs: UserPreferences, _auth: None = Depends(_verify_api_key)):
    state = get_state_manager()
    state.save_preferences(prefs)
    return {"status": "ok"}


@app.get("/preferences")
def get_preferences(_auth: None = Depends(_verify_api_key)):
    state = get_state_manager()
    prefs = state.load_preferences()
    if not prefs:
        return UserPreferences().model_dump()
    return prefs.model_dump()


# ── Analysis pipeline ─────────────────────────────────────────────────────────


@app.post("/analysis/run")
async def run_analysis(
    background_tasks: BackgroundTasks,
    top_n: int = 10,
    _auth: None = Depends(_verify_api_key),
):
    lock = _get_pipeline_lock()
    if lock.locked():
        raise HTTPException(409, "Анализ уже запущен, подождите завершения")

    if time.monotonic() - _pipeline_last_run < _PIPELINE_COOLDOWN:
        remaining = int(_PIPELINE_COOLDOWN - (time.monotonic() - _pipeline_last_run))
        raise HTTPException(429, f"Подождите {remaining}с перед следующим запуском")

    state = get_state_manager()
    profile = state.load_profile()
    if not profile:
        raise HTTPException(400, "Сначала загрузите резюме")

    async def _run():
        global _pipeline_last_run
        lock = _get_pipeline_lock()
        async with lock:
            try:
                from app.core.pipeline import run_analysis_pipeline

                await run_analysis_pipeline(top_n=top_n)
            except Exception as e:
                logger.error("Pipeline error: {}", e)
            finally:
                _pipeline_last_run = time.monotonic()

    background_tasks.add_task(_run)
    return {"status": "started"}


@app.get("/analysis/status")
def analysis_status() -> dict[str, Any]:
    lock = _get_pipeline_lock()
    return {"running": lock is not None and lock.locked()}


@app.get("/analysis/report")
def get_report(_auth: None = Depends(_verify_api_key)) -> dict[str, Any]:
    state = get_state_manager()
    data = state.load_last_report()
    if not data:
        return {"vacancies": [], "message": "Отчёт ещё не сформирован"}
    return {"vacancies": data}


# ── Stats & utils ─────────────────────────────────────────────────────────────


@app.get("/stats")
def get_stats(_auth: None = Depends(_verify_api_key)) -> dict[str, Any]:
    state = get_state_manager()
    vs = get_vector_store()
    return {
        "vacancies_in_db": vs.get_total_count(),
        "has_resume": state.load_profile() is not None,
        "has_preferences": state.load_preferences() is not None,
    }


@app.delete("/data/clear")
def clear_data(_auth: None = Depends(_verify_api_key)):
    vs = get_vector_store()
    vs.clear()
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

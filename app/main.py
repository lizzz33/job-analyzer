"""
FastAPI backend — основной сервис.
"""

import asyncio
from pathlib import Path
import shutil
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from loguru import logger

from app.core.config import settings
from app.models.schemas import UserPreferences
from app.services.resume_parser import resume_parser
from app.services.state_manager import (
    delete_profile,
    load_last_report,
    load_preferences,
    load_profile,
    save_preferences,
    save_profile,
)
from app.services.vector_store import vector_store

app = FastAPI(
    title="Job Analyzer API",
    description="Ассистент по подбору вакансий",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline_lock = asyncio.Lock()


@app.get("/")
def root():
    return RedirectResponse(url="/docs")


# ── Resume ────────────────────────────────────────────────────────────────────


@app.post("/resume/upload", summary="Загрузить резюме")
async def upload_resume(file: UploadFile = File(...)):
    allowed = {".pdf", ".docx", ".txt"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"Поддерживаемые форматы: {allowed}")

    dest = Path(settings.resumes_path) / f"resume{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        profile = await asyncio.to_thread(resume_parser.parse, dest)
        save_profile(profile)
        return {"status": "ok", "profile": profile.model_dump()}
    except Exception as e:
        logger.error("Resume parse error: {}", e)
        raise HTTPException(500, f"Ошибка парсинга резюме: {e}") from e


@app.get("/resume/profile")
def get_profile():
    profile = load_profile()
    if not profile:
        raise HTTPException(404, "Резюме не загружено")
    return profile.model_dump()


@app.delete("/resume/profile")
def remove_profile():
    delete_profile()
    for ext in (".pdf", ".docx", ".txt"):
        f = Path(settings.resumes_path) / f"resume{ext}"
        if f.exists():
            f.unlink()
    return {"status": "ok"}


# ── Preferences ───────────────────────────────────────────────────────────────


@app.post("/preferences")
def set_preferences(prefs: UserPreferences):
    save_preferences(prefs)
    return {"status": "ok"}


@app.get("/preferences")
def get_preferences():
    prefs = load_preferences()
    if not prefs:
        return UserPreferences().model_dump()
    return prefs.model_dump()


# ── Analysis pipeline ─────────────────────────────────────────────────────────


@app.post("/analysis/run")
async def run_analysis(background_tasks: BackgroundTasks, top_n: int = 10):
    if _pipeline_lock.locked():
        raise HTTPException(409, "Анализ уже запущен, подождите завершения")

    profile = load_profile()
    if not profile:
        raise HTTPException(400, "Сначала загрузите резюме")

    async def _run():
        async with _pipeline_lock:
            try:
                from app.core.pipeline import run_analysis_pipeline

                await run_analysis_pipeline(top_n=top_n)
            except Exception as e:
                logger.error("Pipeline error: {}", e)

    background_tasks.add_task(_run)
    return {"status": "started"}


@app.get("/analysis/status")
def analysis_status() -> dict[str, Any]:
    return {"running": _pipeline_lock.locked()}


@app.get("/analysis/report")
def get_report() -> dict[str, Any]:
    data = load_last_report()
    if not data:
        return {"vacancies": [], "message": "Отчёт ещё не сформирован"}
    return {"vacancies": data}


# ── Stats & utils ─────────────────────────────────────────────────────────────


@app.get("/stats")
def get_stats() -> dict[str, Any]:
    return {
        "vacancies_in_db": vector_store.get_total_count(),
        "has_resume": load_profile() is not None,
        "has_preferences": load_preferences() is not None,
    }


@app.delete("/data/clear")
def clear_data():
    vector_store.clear()
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

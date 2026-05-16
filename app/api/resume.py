from pathlib import Path
import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger

from app.core.config import settings
from app.models.schemas import ResumeProfile
from app.services.resume_parser import resume_parser
from app.services.state_manager import load_profile, save_profile

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.post("/upload", response_model=ResumeProfile)
async def upload_resume(file: UploadFile = File(...)):
    """Загружает резюме, парсит и сохраняет профиль."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type. Allowed: {ALLOWED_EXTENSIONS}")

    dest = Path(settings.resumes_path) / f"resume{suffix}"
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        file.file.close()

    try:
        profile = resume_parser.parse(dest)
    except Exception as e:
        logger.error(f"Resume parse error: {e}")
        raise HTTPException(500, f"Failed to parse resume: {e}") from e

    save_profile(profile)
    return profile


@router.get("/profile", response_model=ResumeProfile)
def get_profile():
    """Возвращает текущий профиль из резюме."""
    profile = load_profile()
    if not profile:
        raise HTTPException(404, "Resume not uploaded yet")
    return profile


@router.delete("/profile")
def delete_profile():
    """Удаляет профиль и файл резюме."""
    from app.services.state_manager import _load_state, _save_state

    state = _load_state()
    state.pop("profile", None)
    _save_state(state)
    for ext in ALLOWED_EXTENSIONS:
        f = Path(settings.resumes_path) / f"resume{ext}"
        if f.exists():
            f.unlink()
    return {"message": "Profile deleted"}

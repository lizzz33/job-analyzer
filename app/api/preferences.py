from fastapi import APIRouter

from app.models.schemas import UserPreferences
from app.services.state_manager import load_preferences, save_preferences

router = APIRouter()


@router.get("", response_model=UserPreferences)
def get_preferences():
    """Возвращает текущие настройки поиска."""
    prefs = load_preferences()
    return prefs or UserPreferences()


@router.post("", response_model=UserPreferences)
def update_preferences(prefs: UserPreferences):
    """Сохраняет настройки поиска."""
    save_preferences(prefs)
    return prefs

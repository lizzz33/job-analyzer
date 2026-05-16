from fastapi import APIRouter
from loguru import logger

from app.models.schemas import UserPreferences
from app.services.hh_fetcher import hh_fetcher
from app.services.state_manager import load_preferences
from app.services.vector_store import vector_store

router = APIRouter()


@router.post("/fetch")
async def fetch_vacancies(queries: list[str] | None = None):
    """
    Парсит вакансии с HH API по заданным запросам (или из профиля).
    Добавляет в ChromaDB.
    """
    prefs = load_preferences() or UserPreferences()
    search_queries = queries or prefs.keywords or ["разработчик"]

    total_new = 0
    total_fetched = 0
    seen_ids: set[str] = set()
    all_vacancies = []

    for query in search_queries[:5]:  # не больше 5 запросов за раз
        try:
            vacancies = await hh_fetcher.fetch_vacancies(query, prefs)
            for v in vacancies:
                if v.id not in seen_ids:
                    seen_ids.add(v.id)
                    all_vacancies.append(v)
            total_fetched += len(vacancies)
        except Exception as e:
            logger.error(f"Fetch error for '{query}': {e}")

    added = vector_store.add_vacancies(all_vacancies)
    total_new += added

    return {
        "fetched": len(all_vacancies),
        "added_to_db": total_new,
        "total_in_db": vector_store.get_total_count(),
    }


@router.get("/stats")
def get_stats():
    """Статистика по базе вакансий."""
    return {
        "total_in_db": vector_store.get_total_count(),
    }


@router.delete("/clear")
def clear_vacancies():
    """Очищает базу вакансий."""
    vector_store.clear()
    return {"message": "Vacancy database cleared"}

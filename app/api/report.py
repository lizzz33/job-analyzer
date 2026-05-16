from fastapi import APIRouter, HTTPException
from loguru import logger

from app.core.pipeline import run_analysis_pipeline
from app.models.schemas import DailyReport
from app.services.state_manager import load_last_report

router = APIRouter()


@router.post("/run", response_model=DailyReport)
async def run_report(top_n: int = 10):
    """
    Запускает полный пайплайн анализа:
    парсинг → Chroma → LLM-ранжирование → отчёт.
    """
    try:
        report = await run_analysis_pipeline(top_n=top_n)
        return report
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(500, f"Analysis failed: {e}") from e


@router.get("/last")
def get_last_report():
    """Возвращает результаты последнего анализа."""
    data = load_last_report()
    if not data:
        raise HTTPException(404, "No report yet. Run /api/report/run first.")
    return {"vacancies": data, "count": len(data)}

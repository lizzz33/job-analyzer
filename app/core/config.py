import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


def _read_secret(path: str) -> str:
    return Path(path).read_text().strip()


class Settings(BaseSettings):
    # GigaChat
    gigachat_api_key: str = Field("", env="GIGACHAT_API_KEY")
    gigachat_scope: str = Field("GIGACHAT_API_PERS", env="GIGACHAT_SCOPE")
    gigachat_model: str = Field("GigaChat-Pro", env="GIGACHAT_MODEL")

    # Scheduler
    daily_report_hour: int = Field(9, env="DAILY_REPORT_HOUR")
    daily_report_minute: int = Field(0, env="DAILY_REPORT_MINUTE")

    # Paths
    chroma_db_path: str = Field("./data/chroma_db", env="CHROMA_DB_PATH")
    resumes_path: str = Field("./data/resumes", env="RESUMES_PATH")

    # API
    api_base_url: str = Field("http://api:8000", env="API_BASE_URL")

    # Secret file paths
    gigachat_api_key_file: str = Field("", env="GIGACHAT_API_KEY_FILE")

    class Config:
        extra = "ignore"

    @model_validator(mode="after")
    def _load_secrets_from_files(self) -> "Settings":
        if self.gigachat_api_key_file and not self.gigachat_api_key:
            self.gigachat_api_key = _read_secret(self.gigachat_api_key_file)
        return self

    def ensure_dirs(self):
        Path(self.chroma_db_path).mkdir(parents=True, exist_ok=True)
        Path(self.resumes_path).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

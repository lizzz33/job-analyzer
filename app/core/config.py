from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(path: str) -> str:
    return Path(path).read_text().strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # GigaChat
    gigachat_api_key: str = Field("", alias="GIGACHAT_API_KEY")
    gigachat_scope: str = Field("GIGACHAT_API_PERS", alias="GIGACHAT_SCOPE")
    gigachat_model: str = Field("GigaChat-Pro", alias="GIGACHAT_MODEL")
    gigachat_ca_cert_path: str = Field("", alias="GIGACHAT_CA_CERT_PATH")

    # Scheduler
    scheduler_enabled: bool = Field(False, alias="SCHEDULER_ENABLED")
    daily_report_hour: int = Field(9, alias="DAILY_REPORT_HOUR")
    daily_report_minute: int = Field(0, alias="DAILY_REPORT_MINUTE")

    # Paths
    chroma_db_path: str = Field("./data/chroma_db", alias="CHROMA_DB_PATH")
    resumes_path: str = Field("./data/resumes", alias="RESUMES_PATH")

    # API
    api_base_url: str = Field("http://api:8000", alias="API_BASE_URL")
    api_key: str = Field("", alias="API_KEY")
    cors_origins: str = Field(
        "http://localhost:8501",
        alias="CORS_ORIGINS",
        description="Comma-separated list of allowed origins",
    )

    # Secret file paths
    gigachat_api_key_file: str = Field("", alias="GIGACHAT_API_KEY_FILE")

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

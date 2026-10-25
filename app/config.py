from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки и секреты — только из переменных окружения (или .env рядом с приложением)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://seed:@localhost:5432/seed"
    jwt_secret: str = ""
    jwt_ttl_hours: int = 12
    jwt_cookie_secure: bool = False
    admin_email: str = ""
    admin_password: str = ""
    ml_url: str = "http://localhost:8000"
    ml_internal_token: str = ""  # общий секрет с ML-сервисом (заголовок X-Internal-Token)
    llm_url: str = "http://localhost:8100"
    llm_internal_token: str = ""  # общий секрет с LLM-сервисом (заголовок X-Internal-Token)
    # API маркетплейсов (мок Влада держит все три на одном адресе); свой адрес на каждый — по желанию
    marketplace_url: str = "http://localhost:8000"
    marketplace_ozon_url: str = ""
    marketplace_wb_url: str = ""
    marketplace_yandex_url: str = ""
    # Нейросеть-классификатор (d1-omni) для операций, которым правила и контрагент не дали категорию
    classifier_url: str = "http://192.168.88.60:8300"
    classifier_enabled: bool = True
    classifier_workers: int = 4
    # Отчёт о качестве по компаниям администраторов: <quality_dir>/latest.json → папка отчёта (пишет ML-шлюз)
    quality_dir: str = "state/quality"
    reports_dir: str = "reports"  # отчёт по датасету участников: <reports_dir>/control
    max_upload_mb: int = 100
    max_dataset_mb: int = 300  # zip или пачка файлов датасета одним запросом


def marketplace_url(settings: Settings, marketplace: str) -> str:
    own = {"ozon": settings.marketplace_ozon_url, "wb": settings.marketplace_wb_url,
           "yandex": settings.marketplace_yandex_url}.get(marketplace, "")
    return own or settings.marketplace_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

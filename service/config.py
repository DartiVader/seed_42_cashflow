"""Настройки сервиса: только из переменных окружения (см. .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    internal_token: str = field(default_factory=lambda: os.environ.get("INTERNAL_TOKEN", ""))
    # без токена сервис закрыт (401); для локальной отладки — ML_AUTH_DISABLED=1
    auth_disabled: bool = field(default_factory=lambda: os.environ.get("ML_AUTH_DISABLED") == "1")
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ML_DATA_DIR", "cashflow_data/cashflow_dataset_participants")))
    models_dir: Path = field(default_factory=lambda: Path(os.environ.get("ML_MODELS_DIR", "models")))
    reports_dir: Path = field(default_factory=lambda: Path(os.environ.get("ML_REPORTS_DIR", "reports")))
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get("ML_STATE_DIR", "state")))
    default_model: str = field(default_factory=lambda: os.environ.get("ML_MODEL_VERSION", "lgbm_net-v2"))
    # воркеры прогноза: у каждого свой ForecastContext (~600 МБ, загрузка ~7 с)
    workers: int = field(default_factory=lambda: _int("ML_WORKERS", 2))
    # сколько запросов может ждать свободного воркера, дальше — 429
    queue_max: int = field(default_factory=lambda: _int("ML_QUEUE_MAX", 16))
    # воркеры фоновых задач (process/retrain): отдельный пул, чтобы не тормозить /forecast
    job_workers: int = field(default_factory=lambda: _int("ML_JOB_WORKERS", 1))
    # процессы контрольного прогона для отчёта о качестве: каждый ~700 МБ, 150 компаний ≈ 15 мин на 3 процесса
    quality_workers: int = field(default_factory=lambda: _int("ML_QUALITY_WORKERS", 3))
    request_timeout_s: float = field(default_factory=lambda: float(os.environ.get("ML_REQUEST_TIMEOUT", 30)))
    service_version: str = "1.3.0"
    contract_version: str = "1.0"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "ml_state.sqlite"


def get_settings() -> Settings:
    return Settings()

"""Единый формат ошибок: {"code", "message"}; message — русский текст для предпринимателя."""
from __future__ import annotations

from ml.forecast.contracts import CompanyClosedError, ForecastError, InvalidStatementError


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def company_not_found() -> ApiError:
    return ApiError(404, "company_not_found", "Компания не найдена.")


def from_forecast_error(e: ForecastError) -> ApiError:
    """ForecastError из ml/ → контрактный код (раздел 0 и 2 ML_API_CONTRACT.md)."""
    text = str(e)
    if isinstance(e, InvalidStatementError):
        return ApiError(422, "bad_statement", text)
    if isinstance(e, CompanyClosedError):
        return ApiError(422, "account_closed", text)
    if text.startswith("Нет данных"):
        return ApiError(422, "no_data", text)
    return ApiError(422, "as_of_out_of_range", text)

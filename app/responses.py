from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Ошибка для фронта: текст показывается предпринимателю как есть."""

    def __init__(self, status: int, message: str, field: str | None = None,
                 errors: list[dict] | None = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or [{"field": field, "message": message}]


def not_found_company() -> ApiError:
    # Чужая и несуществующая компания неотличимы: 404, а не 403
    return ApiError(404, "Компания не найдена")


def method_name(request: Request) -> str:
    endpoint = request.scope.get("endpoint")
    return getattr(endpoint, "__name__", "unknown")


def envelope(request: Request, success: bool, data: Any, errors: list[dict]) -> dict:
    return {
        "localDateTime": datetime.now().isoformat(timespec="seconds"),
        "methodName": method_name(request),
        "success": success,
        "data": data,
        "listErrors": errors,
    }


def ok(request: Request, data: Any = None, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=jsonable_encoder(envelope(request, True, data, [])))


def fail(request: Request, status: int, errors: list[dict]) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope(request, False, None, errors))

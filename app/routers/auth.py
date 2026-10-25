import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection, errors

from app.config import Settings, get_settings
from app.db import get_conn
from app.responses import ApiError, ok
from app.schemas import LoginRequest, RegisterRequest
from app.security import (CurrentUser, check_password, clear_auth_cookie, hash_password, issue_token,
                          normalize_email, set_auth_cookie)

log = logging.getLogger("backend.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

BAD_CREDENTIALS = "Неверный email или пароль"
EMAIL_TAKEN = "Пользователь с таким email уже зарегистрирован"


async def create_user(conn: AsyncConnection, email: str, password: str, is_admin: bool) -> CurrentUser:
    email = normalize_email(email)
    try:
        async with conn.transaction():
            row = await (await conn.execute(
                "INSERT INTO users (email, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id",
                [email, hash_password(password), is_admin])).fetchone()
    except errors.UniqueViolation:
        raise ApiError(409, EMAIL_TAKEN, "email") from None
    log.info("user created user_id=%s is_admin=%s", row["id"], is_admin)
    return CurrentUser(row["id"], email, is_admin)


def auth_response(request: Request, user: CurrentUser, settings: Settings, status: int = 200) -> JSONResponse:
    token, expires_at = issue_token(user.id, settings)
    response = ok(request, {"expiresAt": expires_at.isoformat().replace("+00:00", "Z"), "user": user.to_dto()},
                  status)
    set_auth_cookie(response, token, settings)
    return response


@router.post("/register", status_code=201)
async def register(request: Request, body: RegisterRequest, conn: AsyncConnection = Depends(get_conn),
                   settings: Settings = Depends(get_settings)) -> JSONResponse:
    user = await create_user(conn, body.email, body.password, False)
    return auth_response(request, user, settings, 201)


@router.post("/login")
async def login(request: Request, body: LoginRequest, conn: AsyncConnection = Depends(get_conn),
                settings: Settings = Depends(get_settings)) -> JSONResponse:
    row = await (await conn.execute("SELECT id, email, password_hash, is_admin FROM users WHERE email = %s",
                                    [normalize_email(body.email)])).fetchone()
    if row is None or not check_password(body.password, row["password_hash"]):
        log.info("login failed")
        raise ApiError(401, BAD_CREDENTIALS)
    log.info("login ok user_id=%s", row["id"])
    return auth_response(request, CurrentUser(row["id"], row["email"], row["is_admin"]), settings)


@router.post("/logout")
async def logout(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    response = ok(request, None)
    clear_auth_cookie(response, settings)
    return response

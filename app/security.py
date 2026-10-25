from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Request, Response
from psycopg import AsyncConnection

from app.config import Settings, get_settings
from app.db import get_conn
from app.responses import ApiError

COOKIE_NAME = "access_token"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    is_admin: bool

    def to_dto(self) -> dict:
        return {"id": self.id, "email": self.email, "isAdmin": self.is_admin}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def check_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except ValueError:
        return False


def issue_token(user_id: int, settings: Settings) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.jwt_ttl_hours)
    token = jwt.encode({"sub": str(user_id), "iat": now, "exp": expires_at}, settings.jwt_secret, algorithm="HS256")
    return token, expires_at


def set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=settings.jwt_ttl_hours * 3600, path="/",
                        httponly=True, samesite="lax", secure=settings.jwt_cookie_secure)


def clear_auth_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, "", max_age=0, path="/",
                        httponly=True, samesite="lax", secure=settings.jwt_cookie_secure)


def unauthorized() -> ApiError:
    return ApiError(401, "Войдите в аккаунт, чтобы продолжить")


async def current_user(request: Request, conn: AsyncConnection = Depends(get_conn),
                       settings: Settings = Depends(get_settings)) -> CurrentUser:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise unauthorized()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        raise unauthorized() from None
    row = await (await conn.execute("SELECT id, email, is_admin FROM users WHERE id = %s", [user_id])).fetchone()
    if row is None:
        raise unauthorized()
    user = CurrentUser(row["id"], row["email"], row["is_admin"])
    request.state.user_id = user.id
    return user


async def admin_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise ApiError(403, "Недостаточно прав для этого действия")
    return user

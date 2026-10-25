from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.responses import ok
from app.security import CurrentUser, current_user

router = APIRouter(prefix="/api", tags=["user"])


@router.get("/me")
async def get_current_user(request: Request, user: CurrentUser = Depends(current_user)) -> JSONResponse:
    return ok(request, user.to_dto())

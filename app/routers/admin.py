import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.responses import ok
from app.schemas import ActivateRequest, RetrainRequest
from app.security import CurrentUser, admin_user

log = logging.getLogger("backend.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/models")
async def get_models(request: Request, user: CurrentUser = Depends(admin_user)) -> JSONResponse:
    return ok(request, await request.app.state.ml.models())


@router.post("/models/{name}/activate")
async def activate_model(request: Request, name: str, body: ActivateRequest,
                         user: CurrentUser = Depends(admin_user)) -> JSONResponse:
    result = await request.app.state.ml.activate(name, body.version)
    log.info("model activated user_id=%s model=%s version=%s", user.id, name, body.version)
    return ok(request, result)


@router.post("/models/retrain", status_code=202)
async def retrain_model(request: Request, body: RetrainRequest | None = None,
                        user: CurrentUser = Depends(admin_user)) -> JSONResponse:
    # Неуказанные поля не шлём: у ML свои значения по умолчанию (events="mandatory")
    payload = body.model_dump(exclude_none=True) if body else {}
    result = await request.app.state.ml.retrain(payload)
    log.info("retrain started user_id=%s job_id=%s", user.id, result.get("job_id"))
    return ok(request, result, 202)


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str, user: CurrentUser = Depends(admin_user)) -> JSONResponse:
    return ok(request, await request.app.state.ml.job(job_id))

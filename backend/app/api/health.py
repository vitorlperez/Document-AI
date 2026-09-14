from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.database import database_is_ready

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness(request: Request) -> JSONResponse:
    if database_is_ready(request.app.state.engine):
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

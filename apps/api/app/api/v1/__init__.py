from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.centros_custo import router as centros_custo_router
from app.api.v1.health import router as health_router
from app.api.v1.respostas import router as respostas_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(centros_custo_router, tags=["centros-custo"])
api_router.include_router(respostas_router, tags=["respostas"])

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import CurrentOperator
from app.core.database import get_db
from app.schemas.centro_custo import (
    CentroCustoImportPreview,
    CentroCustoImportRequest,
    CentroCustoImportResult,
    CentroCustoListOut,
)
from app.services.auth_service import registrar_audit
from app.services.centro_custo_import import aplicar_import, listar, montar_preview

router = APIRouter(prefix="/centros-custo")

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=CentroCustoListOut)
async def listar_centros_custo(
    operador: CurrentOperator, db: DbSession
) -> CentroCustoListOut:
    """Lista todos os CCs (autenticado). Consumido pelo painel."""
    _ = operador
    return await listar(db)


@router.post("/import/preview", response_model=CentroCustoImportPreview)
async def preview_import(
    req: CentroCustoImportRequest,
    operador: CurrentOperator,
    db: DbSession,
) -> CentroCustoImportPreview:
    """Pré-validação sem persistência. Exige operador autenticado para evitar
    fingerprinting da estrutura org via tentativas anônimas."""
    _ = operador
    return await montar_preview(db, req.itens)


@router.post("/import/commit", response_model=CentroCustoImportResult)
async def commit_import(
    req: CentroCustoImportRequest,
    operador: CurrentOperator,
    db: DbSession,
) -> CentroCustoImportResult:
    """Persiste o import — operação destrutiva (upsert) registrada na auditoria."""
    preview = await montar_preview(db, req.itens)
    if not preview.valido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"erros": [e.model_dump() for e in preview.erros]},
        )
    resultado = await aplicar_import(db, req.itens)
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="centros_custo_import_commit",
        recurso="centros_custo",
        meta={
            "operador_id": str(operador.id),
            "total": preview.total,
            "criados": resultado.criados,
            "atualizados": resultado.atualizados,
        },
    )
    await db.commit()
    return resultado

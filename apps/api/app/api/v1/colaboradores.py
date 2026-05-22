"""Endpoints de colaboradores (Sprint 2).

- POST /v1/colaboradores/import/preview  — valida payload sem persistir
- POST /v1/colaboradores/import/commit   — persiste, cifrando PII

Endpoints de distribuição e descarte são definidos em seus próprios módulos
(`distribuicao` e `descarte`) para isolar responsabilidades.

Toda operação exige operador autenticado e registra auditoria.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import CurrentOperator
from app.core.database import get_db
from app.schemas.colaborador import (
    ColaboradorImportPreview,
    ColaboradorImportRequest,
    ColaboradorImportResult,
    DescarteRequest,
    DescarteResult,
    DistribuicaoResult,
)
from app.services import colaborador_import as service
from app.services.auth_service import registrar_audit
from app.services.descarte import DescarteError, descartar_colaborador_import
from app.services.distribuicao import distribuir_credenciais

router = APIRouter(prefix="/colaboradores")

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/import/preview", response_model=ColaboradorImportPreview)
async def preview_import(
    req: ColaboradorImportRequest,
    operador: CurrentOperator,
    db: DbSession,
) -> ColaboradorImportPreview:
    _ = operador
    return await service.montar_preview(db, req.itens)


@router.post("/import/commit", response_model=ColaboradorImportResult)
async def commit_import(
    req: ColaboradorImportRequest,
    operador: CurrentOperator,
    db: DbSession,
) -> ColaboradorImportResult:
    preview = await service.montar_preview(db, req.itens)
    if not preview.valido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"erros": [e.model_dump() for e in preview.erros]},
        )
    resultado = await service.aplicar_import(db, req.itens)
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="colaboradores_import_commit",
        recurso="colaborador_import",
        meta={
            "operador_id": str(operador.id),
            "total": preview.total,
            "criados": resultado.criados,
            "atualizados": resultado.atualizados,
        },
    )
    await db.commit()
    return resultado


@router.post("/distribuir", response_model=DistribuicaoResult)
async def distribuir(
    operador: CurrentOperator, db: DbSession
) -> DistribuicaoResult:
    """Gera senhas individuais para todos os colaboradores `pendente`.

    A senha em texto claro aparece apenas nesta resposta (HTTP body) — não
    é persistida nem auditada. O operador é responsável pela entrega física
    e por chamar /descartar quando concluir.
    """
    resultado = await distribuir_credenciais(db)
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="credenciais_distribuidas",
        recurso="credencial",
        meta={
            "operador_id": str(operador.id),
            "total_pendentes": resultado.total_pendentes,
            "distribuidas": resultado.distribuidas,
        },
    )
    await db.commit()
    return resultado


@router.post("/descartar", response_model=DescarteResult)
async def descartar(
    body: DescarteRequest, operador: CurrentOperator, db: DbSession
) -> DescarteResult:
    """Zera a tabela colaborador_import — ação IRREVERSÍVEL.

    Requer `confirmar=true` no body para evitar descarte acidental. Falha com
    409 se há colaboradores em status `pendente`. A trilha de auditoria
    cumpre a cláusula 22 do contrato HCPA (registro imutável das ações
    sensíveis sobre PII).
    """
    if not body.confirmar:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "descarte_nao_confirmado",
                "mensagem": "Envie {\"confirmar\": true} para executar o descarte.",
            },
        )
    try:
        n = await descartar_colaborador_import(db)
    except DescarteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "mensagem": exc.mensagem},
        ) from exc
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="colaborador_import_descartado",
        recurso="colaborador_import",
        meta={"operador_id": str(operador.id), "descartados": n},
    )
    await db.commit()
    return DescarteResult(descartados=n)

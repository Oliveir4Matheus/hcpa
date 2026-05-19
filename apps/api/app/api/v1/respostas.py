"""Endpoints de respostas.

- POST /v1/questionarios/{token_anonimo}/respostas — público, sem autenticação;
  o token é o único segredo do respondente.
- GET /v1/respostas/agregado?centro_custo_id=... — operador autenticado;
  agrega respeitando granularidade condicional e suprime buckets pequenas.

Toda regra de negócio mora em `app.services.resposta_service`; aqui só fazemos:
- mapeamento Pydantic ↔ service
- mapeamento `RespostaError` → HTTPException
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import CurrentOperator
from app.core.database import get_db
from app.schemas.resposta import (
    AgregadoOut,
    SubmissaoRespostasIn,
    SubmissaoRespostasOut,
)
from app.services import resposta_service
from app.services.resposta_service import RespostaError

router = APIRouter(prefix="/questionarios")
agregado_router = APIRouter(prefix="/respostas")

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _http(err: RespostaError) -> HTTPException:
    status_map = {
        "token_invalido": status.HTTP_404_NOT_FOUND,
        "questionario_ja_concluido": status.HTTP_409_CONFLICT,
        "itens_duplicados": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "item_invalido": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "centro_custo_invalido": status.HTTP_404_NOT_FOUND,
        "granularidade_indisponivel": status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    return HTTPException(
        status_code=status_map.get(err.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": err.code, "mensagem": err.mensagem},
    )


@router.post(
    "/{token_anonimo}/respostas",
    response_model=SubmissaoRespostasOut,
    status_code=status.HTTP_201_CREATED,
)
async def submeter(
    token_anonimo: uuid.UUID, body: SubmissaoRespostasIn, db: DbSession
) -> SubmissaoRespostasOut:
    try:
        q = await resposta_service.submeter_respostas(
            db, token_anonimo=token_anonimo, respostas=body.respostas
        )
    except RespostaError as exc:
        raise _http(exc) from exc
    assert q.data_conclusao is not None
    return SubmissaoRespostasOut(
        questionario_id=q.id,
        total_respostas=len(body.respostas),
        data_conclusao=q.data_conclusao,
    )


@agregado_router.get("/agregado", response_model=AgregadoOut)
async def agregado(
    centro_custo_id: uuid.UUID,
    operador: CurrentOperator,
    db: DbSession,
) -> AgregadoOut:
    """Agrega respostas pela bucket correta do CC; suprime se k < 5."""
    _ = operador  # uso futuro em auditoria/escopo
    try:
        return await resposta_service.agregar_respostas_por_cc(
            db, centro_custo_id=centro_custo_id
        )
    except RespostaError as exc:
        raise _http(exc) from exc

"""Endpoint público de submissão de respostas (sem autenticação).

Acesso via `token_anonimo` no path. Toda regra de negócio mora em
`app.services.resposta_service`; aqui só fazemos:
- mapeamento Pydantic ↔ service
- mapeamento `RespostaError` → HTTPException
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.resposta import SubmissaoRespostasIn, SubmissaoRespostasOut
from app.services import resposta_service
from app.services.resposta_service import RespostaError

router = APIRouter(prefix="/questionarios")

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _http(err: RespostaError) -> HTTPException:
    status_map = {
        "token_invalido": status.HTTP_404_NOT_FOUND,
        "questionario_ja_concluido": status.HTTP_409_CONFLICT,
        "itens_duplicados": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "item_invalido": status.HTTP_422_UNPROCESSABLE_CONTENT,
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

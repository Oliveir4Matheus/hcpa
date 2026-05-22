"""Endpoints de respostas e criação de questionários.

- POST /v1/questionarios                                — respondente autenticado;
  cria questionário aplicando granularidade condicional, devolve `token_anonimo`.
- POST /v1/questionarios/{token_anonimo}/respostas      — público, sem autenticação;
  o token é o único segredo do respondente.
- GET /v1/respostas/agregado?centro_custo_id=...        — operador autenticado;
  agrega respeitando granularidade condicional e suprime buckets pequenas.

Toda regra de negócio mora em `app.services.resposta_service` e
`app.services.questionario_service`; aqui só fazemos:
- mapeamento Pydantic ↔ service
- mapeamento de erros → HTTPException
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import CurrentOperator
from app.api.v1.auth_respondente import CurrentRespondente
from app.core.database import get_db
from app.models.core import CentroCusto
from app.schemas.resposta import (
    AgregadoOut,
    QuestionarioCriadoOut,
    SubmissaoRespostasIn,
    SubmissaoRespostasOut,
)
from app.services import questionario_service, resposta_service
from app.services.questionario_service import QuestionarioError
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


def _http_questionario(err: QuestionarioError) -> HTTPException:
    status_map = {
        "granularidade_indisponivel": status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    return HTTPException(
        status_code=status_map.get(err.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": err.code, "mensagem": err.mensagem},
    )


@router.post(
    "",
    response_model=QuestionarioCriadoOut,
    status_code=status.HTTP_201_CREATED,
)
async def criar_questionario_endpoint(
    respondente: CurrentRespondente, db: DbSession
) -> QuestionarioCriadoOut:
    """Cria um Questionario para o respondente autenticado.

    A granularidade (CC vs bloco_predio) é decidida em
    `questionario_service.criar_questionario` segundo `total_colaboradores`
    do CC do respondente. K-anonimato em repouso: para CCs pequenos, NÃO
    persistimos `centro_custo_id` no Questionario — só `bloco_predio`.

    O respondente recebe `token_anonimo` (UUID descorrelacionado da identidade)
    para usar no endpoint público de submissão de respostas. NADA na tabela
    `questionarios` permite reconstruir QUAL respondente fez QUAL questionário.
    """
    cc = await db.get(CentroCusto, respondente.centro_custo_id)
    if cc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "centro_custo_invalido",
                "mensagem": "Centro de custo da credencial não existe.",
            },
        )
    try:
        q = await questionario_service.criar_questionario(db, centro_custo=cc)
    except QuestionarioError as exc:
        raise _http_questionario(exc) from exc
    return QuestionarioCriadoOut(questionario_id=q.id, token_anonimo=q.token_anonimo)


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

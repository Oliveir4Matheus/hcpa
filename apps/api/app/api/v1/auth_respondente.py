"""Endpoints de autenticação do respondente — Sprint 2 #7.

Separados de `app.api.v1.auth` (operador) porque o ciclo de vida é totalmente
diferente: cookie distinto (`hcpa_resp_sessao`), TTL 48h, sem TOTP, sem
revogação manual via logout.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.operacional import Credencial
from app.schemas.respondente import RespondenteLoginRequest, RespondenteLoginResponse
from app.services import respondente_auth
from app.services.respondente_auth import (
    SESSAO_RESPONDENTE_TTL,
    RespondenteAuthError,
    carregar_credencial_por_token,
)

router = APIRouter(prefix="/auth")

COOKIE_RESPONDENTE = "hcpa_resp_sessao"
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _cookie_secure() -> bool:
    return get_settings().api_env != "development"


def _set_cookie(response: Response, token: uuid.UUID) -> None:
    response.set_cookie(
        key=COOKIE_RESPONDENTE,
        value=str(token),
        max_age=int(SESSAO_RESPONDENTE_TTL.total_seconds()),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _http(err: RespondenteAuthError) -> HTTPException:
    status_map = {
        "senha_invalida": status.HTTP_404_NOT_FOUND,
        "sessao_respondente_invalida": status.HTTP_401_UNAUTHORIZED,
        "sessao_respondente_expirada": status.HTTP_401_UNAUTHORIZED,
    }
    return HTTPException(
        status_code=status_map.get(err.code, status.HTTP_401_UNAUTHORIZED),
        detail={"code": err.code, "mensagem": err.mensagem},
    )


async def get_current_respondente(
    db: DbSession,
    sessao_token: Annotated[str | None, Cookie(alias=COOKIE_RESPONDENTE)] = None,
) -> Credencial:
    """Dependência FastAPI: exige sessão de respondente válida."""
    if not sessao_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "sessao_respondente_ausente",
                "mensagem": "Sessão de respondente ausente.",
            },
        )
    try:
        token = uuid.UUID(sessao_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "sessao_respondente_invalida",
                "mensagem": "Cookie de sessão malformado.",
            },
        ) from exc
    try:
        return await carregar_credencial_por_token(db, token=token)
    except RespondenteAuthError as exc:
        raise _http(exc) from exc


CurrentRespondente = Annotated[Credencial, Depends(get_current_respondente)]


@router.post("/respondente", response_model=RespondenteLoginResponse)
async def login(
    body: RespondenteLoginRequest, response: Response, db: DbSession
) -> RespondenteLoginResponse:
    try:
        sessao = await respondente_auth.login_respondente(db, senha=body.senha)
    except RespondenteAuthError as exc:
        raise _http(exc) from exc
    _set_cookie(response, sessao.token)
    return RespondenteLoginResponse(token_sessao=sessao.token, expira_em=sessao.expira_em)

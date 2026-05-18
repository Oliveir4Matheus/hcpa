"""Endpoints de autenticação do operador.

Toda regra de negócio mora em `app.services.auth_service`. Aqui só fazemos:
- mapeamento Pydantic ↔ service
- mapeamento `AuthError` → HTTPException
- gestão do cookie de sessão (set/clear)
- extração de IP/User-Agent
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.operacional import Operador
from app.schemas.auth import (
    LoginRequest,
    LoginRespostaCompleta,
    LoginRespostaTotpPendente,
    MensagemSimples,
    OperadorOut,
    TotpConfirmRequest,
    TotpSetupResponse,
    TotpVerifyRequest,
)
from app.services import auth_service
from app.services.auth_service import (
    PENDENTE_TOTP_TTL,
    SESSAO_ATIVA_TTL,
    AuthError,
    carregar_operador_ativo,
)

router = APIRouter(prefix="/auth")

COOKIE_NOME = "hcpa_admin_sessao"
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _cookie_secure() -> bool:
    return get_settings().api_env != "development"


def _set_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    response.set_cookie(
        key=COOKIE_NOME,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NOME, path="/")


def _http(err: AuthError, default_status: int = status.HTTP_401_UNAUTHORIZED) -> HTTPException:
    status_map = {
        "operador_inativo": status.HTTP_403_FORBIDDEN,
        "operador_inexistente": status.HTTP_401_UNAUTHORIZED,
        "credenciais_invalidas": status.HTTP_401_UNAUTHORIZED,
        "sessao_invalida": status.HTTP_401_UNAUTHORIZED,
        "sessao_estado_invalido": status.HTTP_401_UNAUTHORIZED,
        "sessao_revogada": status.HTTP_401_UNAUTHORIZED,
        "sessao_expirada": status.HTTP_401_UNAUTHORIZED,
        "totp_invalido": status.HTTP_401_UNAUTHORIZED,
        "totp_nao_configurado": status.HTTP_409_CONFLICT,
        "email_em_uso": status.HTTP_409_CONFLICT,
    }
    return HTTPException(
        status_code=status_map.get(err.code, default_status),
        detail={"code": err.code, "mensagem": err.mensagem},
    )


async def get_current_operator(
    db: DbSession,
    sessao_token: Annotated[str | None, Cookie(alias=COOKIE_NOME)] = None,
) -> Operador:
    """Dependência FastAPI: exige sessão ATIVA, retorna o Operador."""
    if not sessao_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "sessao_ausente", "mensagem": "Sessão ausente."},
        )
    try:
        return await carregar_operador_ativo(db, token=sessao_token)
    except AuthError as exc:
        raise _http(exc) from exc


CurrentOperator = Annotated[Operador, Depends(get_current_operator)]


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.post(
    "/login",
    response_model=LoginRespostaCompleta | LoginRespostaTotpPendente,
)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> LoginRespostaCompleta | LoginRespostaTotpPendente:
    ip, ua = _client_meta(request)
    try:
        resultado = await auth_service.login(
            db,
            email=body.email,
            senha=body.senha,
            ip_origem=ip,
            user_agent=ua,
        )
    except AuthError as exc:
        raise _http(exc) from exc

    if resultado.totp_pendente:
        _set_cookie(response, resultado.token_sessao, int(PENDENTE_TOTP_TTL.total_seconds()))
        return LoginRespostaTotpPendente(email=resultado.operador.email)

    _set_cookie(response, resultado.token_sessao, int(SESSAO_ATIVA_TTL.total_seconds()))
    return LoginRespostaCompleta(
        operador=OperadorOut(**auth_service.operador_dict(resultado.operador))
    )


@router.post("/totp/verify", response_model=LoginRespostaCompleta)
async def verify_totp(
    body: TotpVerifyRequest,
    response: Response,
    db: DbSession,
    sessao_token: Annotated[str | None, Cookie(alias=COOKIE_NOME)] = None,
) -> LoginRespostaCompleta:
    if not sessao_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "sessao_ausente", "mensagem": "Sessão ausente."},
        )
    try:
        resultado = await auth_service.verificar_totp_login(
            db, token=sessao_token, codigo=body.codigo
        )
    except AuthError as exc:
        raise _http(exc) from exc
    _set_cookie(response, resultado.token_sessao, int(SESSAO_ATIVA_TTL.total_seconds()))
    return LoginRespostaCompleta(
        operador=OperadorOut(**auth_service.operador_dict(resultado.operador))
    )


@router.post("/logout", response_model=MensagemSimples)
async def logout(
    response: Response,
    db: DbSession,
    sessao_token: Annotated[str | None, Cookie(alias=COOKIE_NOME)] = None,
) -> MensagemSimples:
    if sessao_token:
        await auth_service.logout(db, token=sessao_token)
    _clear_cookie(response)
    return MensagemSimples(detalhe="Sessão encerrada.")


@router.get("/me", response_model=OperadorOut)
async def me(operador: CurrentOperator) -> OperadorOut:
    return OperadorOut(**auth_service.operador_dict(operador))


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def setup_totp(operador: CurrentOperator, db: DbSession) -> TotpSetupResponse:
    secret, uri = await auth_service.setup_totp(db, operador=operador)
    return TotpSetupResponse(secret=secret, provisioning_uri=uri)


@router.post("/totp/confirm", response_model=MensagemSimples)
async def confirm_totp(
    body: TotpConfirmRequest, operador: CurrentOperator, db: DbSession
) -> MensagemSimples:
    try:
        await auth_service.confirmar_totp(db, operador=operador, codigo=body.codigo)
    except AuthError as exc:
        raise _http(exc) from exc
    return MensagemSimples(detalhe="TOTP habilitado.")

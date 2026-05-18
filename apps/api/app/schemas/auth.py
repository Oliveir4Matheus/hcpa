"""Schemas Pydantic do fluxo de autenticação do operador.

`LoginResponse` é uma união discriminada: ou retorna o operador (sem TOTP)
ou indica que TOTP é necessário, exigindo segunda chamada em /v1/auth/totp/verify.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=1)


class TotpVerifyRequest(BaseModel):
    codigo: str = Field(min_length=6, max_length=8)


class TotpConfirmRequest(BaseModel):
    codigo: str = Field(min_length=6, max_length=8)


class OperadorOut(BaseModel):
    id: uuid.UUID
    email: str
    nome: str | None
    sobrenome: str | None
    totp_enabled: bool
    ativo: bool
    criado_em: datetime


class LoginRespostaCompleta(BaseModel):
    """TOTP não obrigatório — sessão já está ativa, cookie foi setado."""

    totp_required: Literal[False] = False
    operador: OperadorOut


class LoginRespostaTotpPendente(BaseModel):
    """Senha aceita; aguardando verificação TOTP. Cookie da sessão pendente foi setado."""

    totp_required: Literal[True] = True
    email: str


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MensagemSimples(BaseModel):
    detalhe: str

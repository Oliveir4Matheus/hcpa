"""Schemas do fluxo de autenticação do respondente.

Diferente do operador, o respondente:
- Não tem email; identifica-se apenas pela senha individual gerada na distribuição.
- A sessão tem TTL de 48h (uma única tentativa de questionário).
- Não há TOTP — totem PWA é controlado por proximidade física.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RespondenteLoginRequest(BaseModel):
    senha: str = Field(min_length=1, max_length=64)


class RespondenteLoginResponse(BaseModel):
    token_sessao: uuid.UUID
    expira_em: datetime

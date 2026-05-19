"""Schemas da submissão pública de respostas a um questionário.

Sem PII no payload — o respondente é referenciado apenas pelo `token_anonimo`
do questionário, gerado por `gen_random_uuid()` e descorrelacionado da
identidade do colaborador (§5/§6 da documentação técnica v1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RespostaIn(BaseModel):
    item_id: uuid.UUID
    valor: int = Field(ge=0, le=4)


class SubmissaoRespostasIn(BaseModel):
    respostas: list[RespostaIn] = Field(min_length=1)


class SubmissaoRespostasOut(BaseModel):
    questionario_id: uuid.UUID
    total_respostas: int
    data_conclusao: datetime

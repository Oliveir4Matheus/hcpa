"""Schemas da submissão pública de respostas e da agregação por CC.

Submissão: sem PII no payload — o respondente é referenciado apenas pelo
`token_anonimo` do questionário, gerado por `gen_random_uuid()` e
descorrelacionado da identidade do colaborador (§5/§6 da doc técnica v1).

Agregação: respeita a granularidade condicional do Questionario — CCs
pequenos (`total_colaboradores < K_ANONIMATO_MIN`) caem para `bloco_predio`,
e qualquer agregação com `n_questionarios < K_ANONIMATO_MIN` é suprimida
para preservar k-anonimato no momento da consulta.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QuestionarioCriadoOut(BaseModel):
    """Resposta da criação de questionário pelo respondente.

    Retorna o `token_anonimo` — segredo descorrelacionado da identidade do
    respondente que ele usa para submeter as respostas via endpoint público
    `POST /v1/questionarios/{token}/respostas`.
    """

    questionario_id: uuid.UUID
    token_anonimo: uuid.UUID


class RespostaIn(BaseModel):
    item_id: uuid.UUID
    valor: int = Field(ge=0, le=4)


class SubmissaoRespostasIn(BaseModel):
    respostas: list[RespostaIn] = Field(min_length=1)


class SubmissaoRespostasOut(BaseModel):
    questionario_id: uuid.UUID
    total_respostas: int
    data_conclusao: datetime


class AgregadoBucket(BaseModel):
    """Identifica o grão real da agregação.

    `tipo="centro_custo"` em CCs grandes; `tipo="bloco_predio"` quando o CC
    é pequeno demais e os questionários caem no bloco do prédio.
    """

    tipo: Literal["centro_custo", "bloco_predio"]
    valor: str


class AgregadoDominio(BaseModel):
    dominio_id: uuid.UUID
    dominio_nome: str
    n_respostas: int
    media_valor: float


class AgregadoSupressao(BaseModel):
    motivo: Literal["k_anonimato_insuficiente"]
    minimo_requerido: int
    n_atual: int


class AgregadoOut(BaseModel):
    centro_custo_id: uuid.UUID
    bucket: AgregadoBucket
    n_questionarios: int
    por_dominio: list[AgregadoDominio]
    supressao: AgregadoSupressao | None

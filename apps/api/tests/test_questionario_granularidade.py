"""Integration tests da granularidade condicional CC↔Questionario (k-anonimato).

Cobre as três rotas do `criar_questionario` (CC grande grava FK; CC pequeno
grava bloco; CC pequeno sem bloco falha com code estável) e o invariante
de banco (check XOR rejeita ambos NULL e ambos preenchidos).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto, Questionario
from app.services.questionario_service import (
    K_ANONIMATO_MIN,
    QuestionarioError,
    criar_questionario,
)


async def _cc(
    db: AsyncSession,
    *,
    total: int,
    bloco: str | None = "Bloco A",
) -> CentroCusto:
    cc = CentroCusto(
        codigo=f"CC-{uuid.uuid4().hex[:8]}",
        nome="CC teste",
        bloco_predio=bloco,
        total_colaboradores=total,
    )
    db.add(cc)
    await db.flush()
    return cc


async def test_cc_no_limiar_grava_centro_custo_id(db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=K_ANONIMATO_MIN)
    q = await criar_questionario(db_session, centro_custo=cc)
    assert q.centro_custo_id == cc.id
    assert q.bloco_predio is None


async def test_cc_grande_grava_centro_custo_id(db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=42)
    q = await criar_questionario(db_session, centro_custo=cc)
    assert q.centro_custo_id == cc.id
    assert q.bloco_predio is None


async def test_cc_pequeno_grava_apenas_bloco_predio(db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=K_ANONIMATO_MIN - 1, bloco="Bloco X")
    q = await criar_questionario(db_session, centro_custo=cc)
    assert q.centro_custo_id is None
    assert q.bloco_predio == "Bloco X"


async def test_cc_pequeno_sem_bloco_levanta_code_estavel(db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=2, bloco=None)
    with pytest.raises(QuestionarioError) as exc:
        await criar_questionario(db_session, centro_custo=cc)
    assert exc.value.code == "granularidade_indisponivel"
    assert cc.codigo in exc.value.mensagem


async def test_db_rejeita_ambos_nulos(db_session: AsyncSession) -> None:
    db_session.add(Questionario())  # ambos None
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_db_rejeita_ambos_preenchidos(db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=10, bloco="Bloco Y")
    db_session.add(
        Questionario(centro_custo_id=cc.id, bloco_predio="Bloco Y")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()

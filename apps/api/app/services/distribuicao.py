"""Geração de credenciais individuais — Sprint 2 #6.

Para cada `ColaboradorImport` com status `pendente`:
1. gera senha aleatória legível (alta entropia, sem caracteres ambíguos)
2. argon2id da senha → grava em `credencial.senha_hash` (PK)
3. atualiza `colaborador_import.status_distribuicao = distribuida`

A senha em texto claro só existe na resposta da API e nunca é persistida.
O operador é responsável pela entrega física aos colaboradores.

Após a entrega confirmada, o operador chama o endpoint de descarte
(`/v1/colaboradores/descartar`, Sprint 2 #9) — `credencial` sobrevive,
`colaborador_import` é zerada.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_sha256
from app.core.security import hash_senha
from app.models._base import StatusDistribuicao
from app.models.operacional import ColaboradorImport, Credencial
from app.schemas.colaborador import DistribuicaoCredencial, DistribuicaoResult

# 12 chars de alfabeto sem ambíguos (0/O/o, 1/l/I) — ~63 bits de entropia,
# suficiente para um único uso de boas-vindas. Argon2id no banco.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_TAMANHO_SENHA = 12


def gerar_senha() -> str:
    """Senha aleatória legível para entrega física aos colaboradores."""
    return "".join(secrets.choice(_ALFABETO) for _ in range(_TAMANHO_SENHA))


async def distribuir_credenciais(db: AsyncSession) -> DistribuicaoResult:
    """Processa todos os `pendente` e devolve as senhas em texto claro.

    Idempotente: rodar duas vezes seguidas — a segunda chamada devolve
    `distribuidas=0` se nada estava `pendente` entre as duas. Cada chamada
    é uma única transação; se algo falhar, nenhum status muda.
    """
    pendentes = (
        (
            await db.execute(
                select(ColaboradorImport).where(
                    ColaboradorImport.status_distribuicao == StatusDistribuicao.pendente
                )
            )
        )
        .scalars()
        .all()
    )

    credenciais_resposta: list[DistribuicaoCredencial] = []
    for col in pendentes:
        senha = gerar_senha()
        hash_ = hash_senha(senha)
        db.add(
            Credencial(
                senha_hash=hash_,
                senha_hmac=hmac_sha256(senha),
                centro_custo_id=col.centro_custo_id,
            )
        )
        col.senha_hash = hash_
        col.status_distribuicao = StatusDistribuicao.distribuida
        credenciais_resposta.append(
            DistribuicaoCredencial(matricula=col.matricula, senha=senha)
        )

    await db.flush()
    await db.commit()
    return DistribuicaoResult(
        total_pendentes=len(pendentes),
        distribuidas=len(credenciais_resposta),
        credenciais=credenciais_resposta,
    )

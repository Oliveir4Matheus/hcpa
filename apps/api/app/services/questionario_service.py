"""Criação de Questionario com granularidade condicional (k-anonimato em repouso).

Para CCs com menos de K_ANONIMATO_MIN colaboradores, gravamos apenas
`bloco_predio` no Questionario e omitimos `centro_custo_id`. Mesmo um operador
com acesso direto ao banco não consegue ler granularidade fina nesses casos.

Esta regra é descrita na §5 ("K-anonimato no banco") e §6 da documentação
técnica v1 enviada à HMind em 13/05.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto, Questionario

K_ANONIMATO_MIN = 5


class QuestionarioError(Exception):
    """Falha controlada na criação de questionario. `code` é estável."""

    def __init__(self, code: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.code = code
        self.mensagem = mensagem


async def criar_questionario(
    db: AsyncSession,
    *,
    centro_custo: CentroCusto,
) -> Questionario:
    """Aplica a regra de granularidade e persiste o Questionario.

    - CC com `total_colaboradores >= K_ANONIMATO_MIN`: grava `centro_custo_id`.
    - CC menor: grava apenas `bloco_predio`. Exige `centro_custo.bloco_predio`
      preenchido — caso contrário levanta `granularidade_indisponivel`, pois
      sem bloco não há granularidade superior para cair.
    """
    if centro_custo.total_colaboradores >= K_ANONIMATO_MIN:
        q = Questionario(centro_custo_id=centro_custo.id)
    else:
        if not centro_custo.bloco_predio:
            raise QuestionarioError(
                "granularidade_indisponivel",
                (
                    f"Centro de custo {centro_custo.codigo} tem "
                    f"{centro_custo.total_colaboradores} colaboradores "
                    f"(< {K_ANONIMATO_MIN}) e não possui bloco_predio para "
                    "granularidade superior."
                ),
            )
        q = Questionario(bloco_predio=centro_custo.bloco_predio)

    db.add(q)
    await db.flush()
    await db.commit()
    return q

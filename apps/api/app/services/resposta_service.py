"""Operações sobre respostas — submissão pública e agregação para o painel.

Submissão (pública, via `token_anonimo`):
- O token é o único segredo do respondente e é descorrelacionado da identidade.
- `submetida_em` é arredondado para o início da hora para não revelar timing
  fino (§5 da doc técnica v1).
- Idempotência: questionários em estado != `iniciado` rejeitam com code estável
  `questionario_ja_concluido`.

Agregação (interna, operador autenticado):
- Respeita a granularidade gravada no Questionario (`centro_custo_id` ou
  `bloco_predio`).
- Aplica k-anonimato na consulta também: se a bucket tem
  `n_questionarios < K_ANONIMATO_MIN`, retorna estrutura suprimida em vez
  de expor uma agregação de poucas pessoas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import QuestionarioStatus
from app.models.core import CentroCusto, Dominio, Item, Questionario, Resposta
from app.schemas.resposta import (
    AgregadoBucket,
    AgregadoDominio,
    AgregadoOut,
    AgregadoSupressao,
    RespostaIn,
)
from app.services.auth_service import registrar_audit
from app.services.questionario_service import K_ANONIMATO_MIN


class RespostaError(Exception):
    """Falha controlada na submissão de respostas. `code` é estável."""

    def __init__(self, code: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.code = code
        self.mensagem = mensagem


def _agora_em_hora() -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


async def submeter_respostas(
    db: AsyncSession,
    *,
    token_anonimo: uuid.UUID,
    respostas: list[RespostaIn],
) -> Questionario:
    q = (
        await db.execute(
            select(Questionario).where(Questionario.token_anonimo == token_anonimo)
        )
    ).scalar_one_or_none()
    if q is None:
        raise RespostaError("token_invalido", "Questionário não encontrado.")

    if q.status != QuestionarioStatus.iniciado:
        raise RespostaError(
            "questionario_ja_concluido",
            f"Questionário já está no estado '{q.status.value}'.",
        )

    item_ids = [r.item_id for r in respostas]
    if len(set(item_ids)) != len(item_ids):
        raise RespostaError(
            "itens_duplicados", "Não envie o mesmo item_id mais de uma vez."
        )

    existentes = set(
        (await db.execute(select(Item.id).where(Item.id.in_(item_ids))))
        .scalars()
        .all()
    )
    faltando = [i for i in item_ids if i not in existentes]
    if faltando:
        raise RespostaError(
            "item_invalido",
            f"Itens não existentes: {', '.join(str(i) for i in faltando[:5])}",
        )

    hora = _agora_em_hora()
    for r in respostas:
        db.add(
            Resposta(
                questionario_id=q.id,
                item_id=r.item_id,
                valor=r.valor,
                submetida_em=hora,
            )
        )
    q.status = QuestionarioStatus.concluido
    q.data_conclusao = hora
    await db.flush()
    await registrar_audit(
        db,
        usuario="anonimo",
        acao="respostas_submetidas",
        recurso="questionarios",
        meta={"questionario_id": str(q.id), "n_respostas": len(respostas)},
    )
    await db.commit()
    return q


async def agregar_respostas_por_cc(
    db: AsyncSession,
    *,
    centro_custo_id: uuid.UUID,
) -> AgregadoOut:
    """Agrega respostas pela bucket correta para o CC (k-anonimato em consulta).

    - CC grande (`total_colaboradores >= K_ANONIMATO_MIN`): bucket é o próprio CC.
    - CC pequeno: bucket é `bloco_predio`. Sem bloco definido →
      `granularidade_indisponivel` (mesmo invariante da gravação).

    Em ambos os casos, se a bucket reunir menos de `K_ANONIMATO_MIN`
    questionários concluídos, retorna estrutura suprimida.
    """
    cc = await db.get(CentroCusto, centro_custo_id)
    if cc is None:
        raise RespostaError("centro_custo_invalido", "Centro de custo não encontrado.")

    if cc.total_colaboradores >= K_ANONIMATO_MIN:
        bucket = AgregadoBucket(tipo="centro_custo", valor=str(cc.id))
        bucket_filtro = Questionario.centro_custo_id == cc.id
    else:
        if not cc.bloco_predio:
            raise RespostaError(
                "granularidade_indisponivel",
                f"CC {cc.codigo} é pequeno e não possui bloco_predio.",
            )
        bucket = AgregadoBucket(tipo="bloco_predio", valor=cc.bloco_predio)
        bucket_filtro = Questionario.bloco_predio == cc.bloco_predio

    questionario_ids = (
        (
            await db.execute(
                select(Questionario.id).where(
                    bucket_filtro,
                    Questionario.status == QuestionarioStatus.concluido,
                )
            )
        )
        .scalars()
        .all()
    )
    n = len(questionario_ids)

    if n < K_ANONIMATO_MIN:
        return AgregadoOut(
            centro_custo_id=cc.id,
            bucket=bucket,
            n_questionarios=n,
            por_dominio=[],
            supressao=AgregadoSupressao(
                motivo="k_anonimato_insuficiente",
                minimo_requerido=K_ANONIMATO_MIN,
                n_atual=n,
            ),
        )

    rows = (
        await db.execute(
            select(
                Dominio.id,
                Dominio.nome,
                func.count(Resposta.id),
                func.avg(Resposta.valor),
            )
            .join(Item, Item.dominio_id == Dominio.id)
            .join(Resposta, Resposta.item_id == Item.id)
            .where(Resposta.questionario_id.in_(questionario_ids))
            .group_by(Dominio.id, Dominio.nome)
            .order_by(Dominio.ordem_apresentacao)
        )
    ).all()

    return AgregadoOut(
        centro_custo_id=cc.id,
        bucket=bucket,
        n_questionarios=n,
        por_dominio=[
            AgregadoDominio(
                dominio_id=row[0],
                dominio_nome=row[1],
                n_respostas=int(row[2]),
                media_valor=float(row[3]),
            )
            for row in rows
        ],
        supressao=None,
    )

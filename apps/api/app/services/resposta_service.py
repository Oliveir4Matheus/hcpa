"""Submissão pública de respostas a um questionário, via `token_anonimo`.

Sem autenticação — o token é o único segredo do respondente e é descorrelacionado
da identidade. `submetida_em` é arredondado para o início da hora para não
revelar timing fino do respondente (§5 da documentação técnica v1).

Idempotência: questionários em estado diferente de `iniciado` rejeitam novas
submissões com code estável `questionario_ja_concluido`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import QuestionarioStatus
from app.models.core import Item, Questionario, Resposta
from app.schemas.resposta import RespostaIn
from app.services.auth_service import registrar_audit


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

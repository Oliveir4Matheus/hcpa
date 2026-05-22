"""Descarte da tabela colaborador_import — Sprint 2 #9.

Ação irreversível por design: após a distribuição confirmada das credenciais,
a tabela de ligação entre identidade (matrícula, nome, email) e centro de
custo é zerada. A partir daí, sobra apenas `credencial` — que liga senha-hash
a CC, sem nenhum elo com identidade.

Invariantes mantidos:
- `credencial` permanece intacta (linhas e PII zero, só hash + CC).
- Trilha de auditoria registra a ação com contadores e operador responsável.
- Lembretes sobrevivem (FK removida na migration `4d8f1e6c9b33`).
- Pré-condição: nenhum colaborador pode estar em `pendente` (i.e. com senha
  não emitida) — descartar antes de distribuir é um bug de procedimento.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import StatusDistribuicao
from app.models.operacional import ColaboradorImport


class DescarteError(Exception):
    """Falha controlada no descarte. `code` é estável."""

    def __init__(self, code: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.code = code
        self.mensagem = mensagem


async def descartar_colaborador_import(db: AsyncSession) -> int:
    """Apaga todas as linhas de colaborador_import.

    Retorna a quantidade de linhas removidas. Falha se houver colaborador em
    status `pendente` (senha ainda não distribuída).
    """
    pendentes_n = (
        await db.execute(
            select(ColaboradorImport.matricula).where(
                ColaboradorImport.status_distribuicao == StatusDistribuicao.pendente
            )
        )
    ).scalars().all()
    if pendentes_n:
        raise DescarteError(
            "descarte_com_pendentes",
            (
                f"Há {len(pendentes_n)} colaborador(es) em status 'pendente'. "
                "Distribua as credenciais antes do descarte."
            ),
        )

    total = (
        await db.execute(select(ColaboradorImport.matricula))
    ).scalars().all()
    n = len(total)
    if n == 0:
        # idempotência: tabela já vazia → no-op, mas auditado pelo handler.
        return 0

    await db.execute(delete(ColaboradorImport))
    await db.flush()
    return n

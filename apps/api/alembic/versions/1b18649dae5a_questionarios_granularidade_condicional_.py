"""questionarios_granularidade_condicional_k_anonimato

Revision ID: 1b18649dae5a
Revises: f68810e21415
Create Date: 2026-05-18 15:24:57.488008

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b18649dae5a'
down_revision: str | Sequence[str] | None = 'f68810e21415'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adiciona bloco_predio antes de afrouxar centro_custo_id pra não deixar
    # nenhuma linha existente fora do XOR (linhas atuais têm CC preenchido).
    op.add_column(
        "questionarios",
        sa.Column("bloco_predio", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_questionarios_bloco_predio",
        "questionarios",
        ["bloco_predio"],
    )
    op.alter_column("questionarios", "centro_custo_id", nullable=True)
    op.create_check_constraint(
        "ck_questionarios_granularidade_xor",
        "questionarios",
        "(centro_custo_id IS NULL) <> (bloco_predio IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_questionarios_granularidade_xor", "questionarios", type_="check"
    )
    # Não há linhas com centro_custo_id NULL antes do upgrade — se houver,
    # downgrade vai falhar com erro de NOT NULL, o que é o comportamento desejado
    # (você teria que migrar manualmente os dados de bloco_predio para CC antes).
    op.alter_column("questionarios", "centro_custo_id", nullable=False)
    op.drop_index("ix_questionarios_bloco_predio", table_name="questionarios")
    op.drop_column("questionarios", "bloco_predio")

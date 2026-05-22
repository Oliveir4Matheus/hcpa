"""credencial: senha_hmac + expira_em; lembretes: solta FK em colaborador_import

Revision ID: 4d8f1e6c9b33
Revises: 3a8d6b1c5e22
Create Date: 2026-05-21 10:00:00.000000

Sprint 2 introduz três mudanças interligadas:

1. `credencial.senha_hmac BYTEA UNIQUE NOT NULL`
   Lookup O(1) no login do respondente — argon2id puro no `senha_hash` exigiria
   iteração linear. HMAC-SHA256 determinístico só localiza a linha; argon2id
   continua sendo a barreira primária.

2. `credencial.expira_em TIMESTAMPTZ NULL`
   TTL 48h do `token_sessao_temporario` (já existente). NULL até primeiro login.

3. Solta FK `lembretes.matricula → colaborador_import.matricula`
   `colaborador_import` é descartada após distribuição (Sprint 2 #9); precisamos
   preservar a trilha de lembretes mesmo após o descarte.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4d8f1e6c9b33'
down_revision: str | Sequence[str] | None = '3a8d6b1c5e22'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. expira_em em credencial (nullable, sem default)
    op.add_column(
        "credencial",
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. senha_hmac — duas etapas para permitir backfill antes do NOT NULL.
    op.add_column(
        "credencial",
        sa.Column("senha_hmac", sa.LargeBinary(), nullable=True),
    )
    # Em prod (Sprint 2) ainda não há linhas em `credencial` — a distribuição
    # acontece após esta migration. Backfill defensivo: linhas órfãs ganham
    # um random bytes para satisfazer UNIQUE; depois NOT NULL.
    op.execute(
        "UPDATE credencial SET senha_hmac = gen_random_bytes(32) WHERE senha_hmac IS NULL"
    )
    op.alter_column(
        "credencial",
        "senha_hmac",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_credencial_senha_hmac", "credencial", ["senha_hmac"]
    )

    # 3. Solta FK em lembretes; coluna `matricula` continua existindo, sem FK.
    op.drop_constraint("lembretes_matricula_fkey", "lembretes", type_="foreignkey")


def downgrade() -> None:
    # Para o downgrade, removemos o que adicionamos e recriamos a FK original.
    op.create_foreign_key(
        "lembretes_matricula_fkey",
        "lembretes",
        "colaborador_import",
        ["matricula"],
        ["matricula"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_credencial_senha_hmac", "credencial", type_="unique")
    op.drop_column("credencial", "senha_hmac")
    op.drop_column("credencial", "expira_em")

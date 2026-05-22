"""colaborador_import: senha_hash nullable até distribuição

Revision ID: 3a8d6b1c5e22
Revises: 2c2f4d9a7e10
Create Date: 2026-05-21 09:30:00.000000

Sprint 2 separa o import (matrícula, CC, PII) da geração de credenciais.
Durante a janela entre o import e o passo "distribuir", `senha_hash` fica
NULL e `status_distribuicao = pendente`. Após `distribuir`, recebe o
argon2id da senha aleatória gerada para esse colaborador.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3a8d6b1c5e22'
down_revision: str | Sequence[str] | None = '2c2f4d9a7e10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "colaborador_import",
        "senha_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill defensivo: NULLs viram string vazia para satisfazer o NOT NULL.
    # Não deve haver NULLs em prod no momento do downgrade, mas o INSERT
    # explícito evita falha no `alter`.
    op.execute(
        "UPDATE colaborador_import SET senha_hash = '' WHERE senha_hash IS NULL"
    )
    op.alter_column(
        "colaborador_import",
        "senha_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )

"""operadores: trigger BEFORE UPDATE para atualizado_em

Revision ID: 2c2f4d9a7e10
Revises: 1b18649dae5a
Create Date: 2026-05-21 09:00:00.000000

O `onupdate=text("now()")` declarado no modelo SQLAlchemy é executado
pelo ORM apenas em UPDATE explícitos via flush — alterações via SQL
bruto ou via update() bypass o ORM. Para garantir o invariante "toda
modificação na linha atualiza atualizado_em" criamos um trigger no
banco que dispara antes de qualquer UPDATE.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c2f4d9a7e10'
down_revision: str | Sequence[str] | None = '1b18649dae5a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Função genérica reaproveitável — qualquer tabela com coluna
    # `atualizado_em timestamptz` pode plugar este trigger no futuro.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_atualizado_em()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.atualizado_em = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_operadores_atualizado_em
        BEFORE UPDATE ON operadores
        FOR EACH ROW
        EXECUTE FUNCTION set_atualizado_em();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_operadores_atualizado_em ON operadores")
    op.execute("DROP FUNCTION IF EXISTS set_atualizado_em()")

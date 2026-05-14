"""Models SQLAlchemy da plataforma HCPA.

Importados aqui para que `Base.metadata` (usado pelo Alembic autogenerate)
enxergue todas as tabelas a partir de um único `import app.models`.
"""

from app.models.core import (
    CentroCusto,
    Dominio,
    Item,
    Questionario,
    Resposta,
)
from app.models.operacional import (
    Auditoria,
    ColaboradorImport,
    Credencial,
    Lembrete,
    SessaoAdmin,
)

__all__ = [
    "Auditoria",
    "CentroCusto",
    "ColaboradorImport",
    "Credencial",
    "Dominio",
    "Item",
    "Lembrete",
    "Questionario",
    "Resposta",
    "SessaoAdmin",
]

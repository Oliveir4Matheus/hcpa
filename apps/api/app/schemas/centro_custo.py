"""Schemas do import de centros de custo — §8.2 da documentação técnica.

O Operador envia a lista vinda do Salesforce; o fluxo é em duas fases
(preview e commit) e a hierarquia é referenciada por `codigo`, não por id.
"""

from pydantic import BaseModel, Field, field_validator


class CentroCustoImportItem(BaseModel):
    codigo: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=200)
    bloco_predio: str | None = Field(default=None, max_length=120)
    codigo_pai: str | None = Field(default=None, max_length=60)
    total_colaboradores: int = Field(default=0, ge=0)

    @field_validator("codigo", "nome", "bloco_predio", "codigo_pai", mode="before")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class CentroCustoImportRequest(BaseModel):
    itens: list[CentroCustoImportItem] = Field(min_length=1)


class CentroCustoImportIssue(BaseModel):
    codigo: str
    erro: str


class CentroCustoImportPreview(BaseModel):
    total: int
    novos: list[str]
    atualizados: list[str]
    erros: list[CentroCustoImportIssue]
    valido: bool


class CentroCustoImportResult(BaseModel):
    criados: int
    atualizados: int

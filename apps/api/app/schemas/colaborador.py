"""Schemas do import de colaboradores e geração de credenciais.

Pipeline da Sprint 2:
    import (matrícula, PII, CC) → distribuir (senha aleatória, argon2id) →
    descartar colaborador_import.

O import é em duas fases (preview/commit) espelhando o de centros de custo:
o operador vê o que será criado/atualizado antes de persistir. PII (nome e
email) nunca trafega em texto claro além do payload de entrada — após o
commit, fica apenas o ciphertext (`*_enc`) via `app.core.crypto`.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class ColaboradorImportItem(BaseModel):
    matricula: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=240)
    email: EmailStr
    centro_custo_codigo: str = Field(min_length=1, max_length=60)

    @field_validator("matricula", "nome", "centro_custo_codigo", mode="before")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class ColaboradorImportRequest(BaseModel):
    itens: list[ColaboradorImportItem] = Field(min_length=1)


class ColaboradorImportIssue(BaseModel):
    matricula: str
    erro: str


class ColaboradorImportPreview(BaseModel):
    total: int
    novos: list[str]
    atualizados: list[str]
    erros: list[ColaboradorImportIssue]
    valido: bool


class ColaboradorImportResult(BaseModel):
    criados: int
    atualizados: int


class DistribuicaoCredencial(BaseModel):
    """Linha do CSV de retorno da distribuição — senha em texto claro.

    A senha NUNCA é persistida em texto claro; só existe nesta resposta para
    que o operador possa entregar aos colaboradores. Após confirmação física
    da entrega, o operador deve descartar a tabela colaborador_import (#9).
    """

    matricula: str
    senha: str


class DistribuicaoResult(BaseModel):
    total_pendentes: int
    distribuidas: int
    credenciais: list[DistribuicaoCredencial]


class DescarteRequest(BaseModel):
    """Confirmação explícita do descarte (operação irreversível)."""

    confirmar: bool = Field(
        ...,
        description=(
            "Precisa ser literalmente true. Evita descarte acidental. "
            "Cláusula 22 do contrato HCPA exige trilha de auditoria explícita."
        ),
    )


class DescarteResult(BaseModel):
    descartados: int

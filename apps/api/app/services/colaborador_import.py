"""Import de colaboradores — Sprint 2 #5.

`montar_preview` valida sem persistir e classifica em novos/atualizados.
`aplicar_import` persiste cifrando PII (nome, email) via app.core.crypto.
A FK para centros_custo é resolvida pelo `codigo` (mesmo padrão do import
de CC), porque o operador trabalha com códigos vindos do Salesforce.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.models.operacional import ColaboradorImport
from app.schemas.colaborador import (
    ColaboradorImportIssue,
    ColaboradorImportItem,
    ColaboradorImportPreview,
    ColaboradorImportResult,
)


async def _matriculas_existentes(db: AsyncSession) -> set[str]:
    result = await db.execute(select(ColaboradorImport.matricula))
    return set(result.scalars().all())


async def _mapa_cc_por_codigo(db: AsyncSession) -> dict[str, CentroCusto]:
    rows = (await db.execute(select(CentroCusto))).scalars().all()
    return {cc.codigo: cc for cc in rows}


def _validar(
    itens: list[ColaboradorImportItem],
    existentes: set[str],
    ccs: dict[str, CentroCusto],
) -> list[ColaboradorImportIssue]:
    erros: list[ColaboradorImportIssue] = []

    vistos: set[str] = set()
    for item in itens:
        if item.matricula in vistos:
            erros.append(
                ColaboradorImportIssue(
                    matricula=item.matricula, erro="matrícula duplicada no payload"
                )
            )
        vistos.add(item.matricula)

    for item in itens:
        if item.centro_custo_codigo not in ccs:
            erros.append(
                ColaboradorImportIssue(
                    matricula=item.matricula,
                    erro=(
                        f"centro_custo_codigo '{item.centro_custo_codigo}' "
                        "não existe — importe os CCs antes dos colaboradores"
                    ),
                )
            )

    _ = existentes  # reservado para futuras regras (ex.: troca de CC bloqueada)
    return erros


async def montar_preview(
    db: AsyncSession, itens: list[ColaboradorImportItem]
) -> ColaboradorImportPreview:
    existentes = await _matriculas_existentes(db)
    ccs = await _mapa_cc_por_codigo(db)
    erros = _validar(itens, existentes, ccs)
    invalidas = {e.matricula for e in erros}

    novos: list[str] = []
    atualizados: list[str] = []
    for item in itens:
        if item.matricula in invalidas:
            continue
        (atualizados if item.matricula in existentes else novos).append(item.matricula)

    return ColaboradorImportPreview(
        total=len(itens),
        novos=novos,
        atualizados=atualizados,
        erros=erros,
        valido=not erros,
    )


async def aplicar_import(
    db: AsyncSession, itens: list[ColaboradorImportItem]
) -> ColaboradorImportResult:
    existentes: dict[str, ColaboradorImport] = {
        c.matricula: c
        for c in (await db.execute(select(ColaboradorImport))).scalars().all()
    }
    ccs = await _mapa_cc_por_codigo(db)

    criados = 0
    atualizados = 0
    for item in itens:
        col = existentes.get(item.matricula)
        if col is None:
            col = ColaboradorImport(matricula=item.matricula)
            db.add(col)
            criados += 1
        else:
            atualizados += 1
        col.centro_custo_id = ccs[item.centro_custo_codigo].id
        # PII cifrada pelas properties do modelo (AES-256-GCM via crypto).
        col.nome = item.nome
        col.email = item.email

    await db.flush()
    await db.commit()
    return ColaboradorImportResult(criados=criados, atualizados=atualizados)

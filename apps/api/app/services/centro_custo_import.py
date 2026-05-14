"""Lógica do import de centros de custo — §8.2 da documentação técnica.

`montar_preview` valida e classifica sem persistir; `aplicar_import` persiste
numa única transação, resolvendo `codigo_pai` → `centro_custo_pai_id` em dois
passos para que pais e filhos do mesmo payload coexistam.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.schemas.centro_custo import (
    CentroCustoImportIssue,
    CentroCustoImportItem,
    CentroCustoImportPreview,
    CentroCustoImportResult,
)


async def _codigos_existentes(db: AsyncSession) -> set[str]:
    result = await db.execute(select(CentroCusto.codigo))
    return set(result.scalars().all())


def _detectar_ciclos(itens: list[CentroCustoImportItem]) -> set[str]:
    """Cada nó tem no máximo um pai — basta seguir a cadeia até repetir."""
    pai = {it.codigo: it.codigo_pai for it in itens}
    em_ciclo: set[str] = set()
    for inicio in pai:
        visto: list[str] = []
        atual: str | None = inicio
        while atual in pai and atual not in visto:
            visto.append(atual)
            atual = pai[atual]
        if atual in pai:  # parou porque reencontrou um nó do caminho
            em_ciclo.update(visto[visto.index(atual):])
    return em_ciclo


def _validar(
    itens: list[CentroCustoImportItem], existentes: set[str]
) -> list[CentroCustoImportIssue]:
    erros: list[CentroCustoImportIssue] = []

    vistos: set[str] = set()
    for item in itens:
        if item.codigo in vistos:
            erros.append(
                CentroCustoImportIssue(codigo=item.codigo, erro="código duplicado no payload")
            )
        vistos.add(item.codigo)

    conhecidos = vistos | existentes
    for item in itens:
        if item.codigo_pai is None:
            continue
        if item.codigo_pai == item.codigo:
            erros.append(
                CentroCustoImportIssue(
                    codigo=item.codigo, erro="centro de custo não pode ser pai de si mesmo"
                )
            )
        elif item.codigo_pai not in conhecidos:
            erros.append(
                CentroCustoImportIssue(
                    codigo=item.codigo,
                    erro=f"código pai '{item.codigo_pai}' não existe no payload nem na base",
                )
            )

    for codigo in sorted(_detectar_ciclos(itens)):
        erros.append(
            CentroCustoImportIssue(codigo=codigo, erro="ciclo na hierarquia de centros de custo")
        )

    return erros


async def montar_preview(
    db: AsyncSession, itens: list[CentroCustoImportItem]
) -> CentroCustoImportPreview:
    existentes = await _codigos_existentes(db)
    erros = _validar(itens, existentes)
    invalidos = {e.codigo for e in erros}

    novos: list[str] = []
    atualizados: list[str] = []
    for item in itens:
        if item.codigo in invalidos:
            continue
        (atualizados if item.codigo in existentes else novos).append(item.codigo)

    return CentroCustoImportPreview(
        total=len(itens),
        novos=novos,
        atualizados=atualizados,
        erros=erros,
        valido=not erros,
    )


async def aplicar_import(
    db: AsyncSession, itens: list[CentroCustoImportItem]
) -> CentroCustoImportResult:
    result = await db.execute(select(CentroCusto))
    existentes: dict[str, CentroCusto] = {cc.codigo: cc for cc in result.scalars().all()}

    mapa: dict[str, CentroCusto] = {}
    criados = 0
    atualizados = 0
    for item in itens:
        cc = existentes.get(item.codigo)
        if cc is None:
            cc = CentroCusto(codigo=item.codigo)
            db.add(cc)
            criados += 1
        else:
            atualizados += 1
        cc.nome = item.nome
        cc.bloco_predio = item.bloco_predio
        cc.total_colaboradores = item.total_colaboradores
        mapa[item.codigo] = cc

    await db.flush()  # garante o id dos centros recém-criados

    for item in itens:
        cc = mapa[item.codigo]
        if item.codigo_pai is None:
            cc.centro_custo_pai_id = None
        else:
            pai = mapa.get(item.codigo_pai) or existentes[item.codigo_pai]
            cc.centro_custo_pai_id = pai.id

    await db.commit()
    return CentroCustoImportResult(criados=criados, atualizados=atualizados)

"""Seed do smoke E2E de submissão + agregação de respostas.

Cria, de forma idempotente, o estado necessário para `scripts/smoke-respostas.sh`:

- Operador `smoke-respostas@example.com` (senha conhecida).
- Domínio `SMOKE Demandas` com 2 itens.
- 4 centros de custo prefixados `SMOKE-`:
    * SMOKE-G  (total=10, Bloco-Smoke-A)        — caminho "centro_custo"
    * SMOKE-P1 (total=2,  Bloco-Smoke-B)        — caminho "bloco_predio"
    * SMOKE-P2 (total=3,  Bloco-Smoke-B)        — completa o bloco P1
    * SMOKE-S  (total=10, Bloco-Smoke-Solitario) — caminho "supressão"
- 5 questionários para SMOKE-G, 2 para SMOKE-P1, 3 para SMOKE-P2, 0 para SMOKE-S.

Imprime JSON em stdout com os dados que o shell precisa para submeter respostas
e validar a agregação. Cleanup é responsabilidade do shell, via `--cleanup`.

Uso (dentro do container):
    docker compose exec -T api python -m scripts.seed_respostas_smoke
    docker compose exec -T api python -m scripts.seed_respostas_smoke --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models.core import CentroCusto, Dominio, Item, Questionario, Resposta
from app.models.operacional import Operador
from app.services.auth_service import AuthError, criar_operador
from app.services.questionario_service import criar_questionario

OPERADOR_EMAIL = "smoke-respostas@example.com"
OPERADOR_SENHA = "senha-smoke-respostas-12345"

CC_DEFS = [
    {"codigo": "SMOKE-G", "nome": "Smoke Grande", "bloco": "Bloco-Smoke-A", "total": 10, "n_q": 5},
    {"codigo": "SMOKE-P1", "nome": "Smoke Pequeno 1", "bloco": "Bloco-Smoke-B", "total": 2, "n_q": 2},
    {"codigo": "SMOKE-P2", "nome": "Smoke Pequeno 2", "bloco": "Bloco-Smoke-B", "total": 3, "n_q": 3},
    {"codigo": "SMOKE-S", "nome": "Smoke Solitário", "bloco": "Bloco-Smoke-Solitario", "total": 10, "n_q": 0},
]

DOMINIO_NOME = "SMOKE Demandas"
ITEM_TEXTOS = ["SMOKE item 1", "SMOKE item 2"]


async def _cleanup(db) -> None:
    """Remove em ordem que respeita FKs (RESTRICT)."""
    cc_ids = (
        await db.execute(
            select(CentroCusto.id).where(CentroCusto.codigo.like("SMOKE-%"))
        )
    ).scalars().all()
    blocos = list({d["bloco"] for d in CC_DEFS})

    q_ids = (
        await db.execute(
            select(Questionario.id).where(
                (Questionario.centro_custo_id.in_(cc_ids))
                | (Questionario.bloco_predio.in_(blocos))
            )
        )
    ).scalars().all()
    if q_ids:
        await db.execute(delete(Resposta).where(Resposta.questionario_id.in_(q_ids)))
        await db.execute(delete(Questionario).where(Questionario.id.in_(q_ids)))

    item_ids = (
        await db.execute(
            select(Item.id).join(Dominio).where(Dominio.nome == DOMINIO_NOME)
        )
    ).scalars().all()
    if item_ids:
        await db.execute(delete(Item).where(Item.id.in_(item_ids)))
    await db.execute(delete(Dominio).where(Dominio.nome == DOMINIO_NOME))

    if cc_ids:
        await db.execute(delete(CentroCusto).where(CentroCusto.id.in_(cc_ids)))

    # operador + sessoes via cascade no relacionamento sessao_admin (ondelete CASCADE)
    await db.execute(delete(Operador).where(Operador.email == OPERADOR_EMAIL))

    await db.commit()


async def _ensure_operador(db) -> None:
    existente = (
        await db.execute(select(Operador).where(Operador.email == OPERADOR_EMAIL))
    ).scalar_one_or_none()
    if existente is not None:
        return
    try:
        await criar_operador(
            db, email=OPERADOR_EMAIL, senha=OPERADOR_SENHA, nome="Smoke", sobrenome="Respostas"
        )
    except AuthError as exc:
        raise SystemExit(f"erro criando operador: {exc.code} — {exc.mensagem}")


async def _ensure_dominio(db) -> tuple[Dominio, list[Item]]:
    dom = (
        await db.execute(select(Dominio).where(Dominio.nome == DOMINIO_NOME))
    ).scalar_one_or_none()
    if dom is None:
        dom = Dominio(nome=DOMINIO_NOME, polaridade=-1, ordem_apresentacao=999)
        db.add(dom)
        await db.flush()
    itens = (
        await db.execute(select(Item).where(Item.dominio_id == dom.id).order_by(Item.ordem_apresentacao))
    ).scalars().all()
    if not itens:
        itens = [
            Item(dominio_id=dom.id, texto_pergunta=t, ordem_apresentacao=i, escala_tipo="A")
            for i, t in enumerate(ITEM_TEXTOS, start=1)
        ]
        for it in itens:
            db.add(it)
        await db.flush()
    await db.commit()
    return dom, list(itens)


async def _ensure_cc(db, *, codigo: str, nome: str, bloco: str, total: int) -> CentroCusto:
    cc = (
        await db.execute(select(CentroCusto).where(CentroCusto.codigo == codigo))
    ).scalar_one_or_none()
    if cc is None:
        cc = CentroCusto(codigo=codigo, nome=nome, bloco_predio=bloco, total_colaboradores=total)
        db.add(cc)
        await db.commit()
        await db.refresh(cc)
    return cc


async def _run(cleanup_only: bool) -> int:
    async with SessionLocal() as db:
        await _cleanup(db)
        if cleanup_only:
            print(json.dumps({"cleanup": "ok"}))
            return 0

        await _ensure_operador(db)
        _, itens = await _ensure_dominio(db)

        saida: dict = {
            "operador": {"email": OPERADOR_EMAIL, "senha": OPERADOR_SENHA},
            "itens": [str(it.id) for it in itens],
            "ccs": {},
        }

        for spec in CC_DEFS:
            cc = await _ensure_cc(
                db,
                codigo=spec["codigo"],
                nome=spec["nome"],
                bloco=spec["bloco"],
                total=spec["total"],
            )
            tokens: list[str] = []
            for _ in range(int(spec["n_q"])):
                q = await criar_questionario(db, centro_custo=cc)
                tokens.append(str(q.token_anonimo))
            saida["ccs"][spec["codigo"]] = {
                "id": str(cc.id),
                "bloco": cc.bloco_predio,
                "total": cc.total_colaboradores,
                "tokens": tokens,
            }

        print(json.dumps(saida))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed do smoke E2E de respostas")
    ap.add_argument("--cleanup", action="store_true", help="apenas remove dados de smoke e sai")
    args = ap.parse_args()
    return asyncio.run(_run(cleanup_only=args.cleanup))


if __name__ == "__main__":
    sys.exit(main())

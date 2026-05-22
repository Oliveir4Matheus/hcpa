"""Integration tests da geração de credenciais (Sprint 2 #6).

Cobre auth, idempotência, criação de `credencial` por colaborador pendente,
verificação argon2id da senha em texto claro retornada, e auditoria sem
vazar senhas no metadata.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_sha256
from app.core.security import verify_senha
from app.models._base import StatusDistribuicao
from app.models.core import CentroCusto
from app.models.operacional import Auditoria, ColaboradorImport, Credencial
from app.services import auth_service

DISTRIBUIR = "/v1/colaboradores/distribuir"
COMMIT = "/v1/colaboradores/import/commit"
COOKIE = "hcpa_admin_sessao"
SENHA_OP = "senha-forte-op-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA_OP)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA_OP})
    assert r.status_code == 200, r.text
    return {COOKIE: r.cookies[COOKIE]}


async def _seed_colaboradores(
    client: AsyncClient,
    cookies: dict[str, str],
    db: AsyncSession,
    *,
    n: int,
) -> tuple[str, list[str]]:
    """Cria CC + n colaboradores via endpoint REST (idempotente, exercita a stack)."""
    codigo = f"CC-DIST-{uuid.uuid4().hex[:6]}"
    cc = CentroCusto(codigo=codigo, nome=codigo, total_colaboradores=n)
    db.add(cc)
    await db.flush()

    matriculas = [f"DIST-{uuid.uuid4().hex[:8]}" for _ in range(n)]
    payload = {
        "itens": [
            {
                "matricula": m,
                "nome": f"Pessoa {i}",
                "email": f"{m.lower()}@example.com",
                "centro_custo_codigo": codigo,
            }
            for i, m in enumerate(matriculas)
        ]
    }
    r = await client.post(COMMIT, json=payload, cookies=cookies)
    assert r.status_code == 200, r.text
    return codigo, matriculas


async def test_distribuir_exige_auth(client: AsyncClient) -> None:
    r = await client.post(DISTRIBUIR)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_ausente"


async def test_distribuir_gera_credenciais_e_atualiza_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="dist1@example.com")
    _, matriculas = await _seed_colaboradores(client, cookies, db_session, n=3)

    r = await client.post(DISTRIBUIR, cookies=cookies)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["distribuidas"] == 3
    assert body["total_pendentes"] == 3
    assert len(body["credenciais"]) == 3

    cred_por_matricula = {c["matricula"]: c["senha"] for c in body["credenciais"]}
    assert set(cred_por_matricula) == set(matriculas)

    # status dos colaboradores virou `distribuida`
    cols = (
        (
            await db_session.execute(
                select(ColaboradorImport).where(
                    ColaboradorImport.matricula.in_(matriculas)
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(c.status_distribuicao == StatusDistribuicao.distribuida for c in cols)
    assert all(c.senha_hash is not None for c in cols)


async def test_senha_retornada_decifra_via_argon2id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="dist2@example.com")
    _, _ = await _seed_colaboradores(client, cookies, db_session, n=1)
    r = await client.post(DISTRIBUIR, cookies=cookies)
    cred = r.json()["credenciais"][0]
    senha_plain = cred["senha"]

    # localiza a Credencial via HMAC determinístico (mesma estratégia do login)
    row = (
        await db_session.execute(
            select(Credencial).where(Credencial.senha_hmac == hmac_sha256(senha_plain))
        )
    ).scalar_one()
    assert verify_senha(senha_plain, row.senha_hash) is True


async def test_distribuir_e_idempotente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="dist3@example.com")
    await _seed_colaboradores(client, cookies, db_session, n=2)

    r1 = await client.post(DISTRIBUIR, cookies=cookies)
    assert r1.json()["distribuidas"] == 2

    r2 = await client.post(DISTRIBUIR, cookies=cookies)
    assert r2.status_code == 200
    body = r2.json()
    assert body["total_pendentes"] == 0
    assert body["distribuidas"] == 0
    assert body["credenciais"] == []


async def test_auditoria_nao_vaza_senhas(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "dist-audit@example.com"
    cookies = await _login(client, db_session, email=email)
    await _seed_colaboradores(client, cookies, db_session, n=2)
    r = await client.post(DISTRIBUIR, cookies=cookies)
    senhas = [c["senha"] for c in r.json()["credenciais"]]

    entries = (
        (
            await db_session.execute(
                select(Auditoria).where(
                    Auditoria.acao == "credenciais_distribuidas",
                    Auditoria.usuario == email,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.meta["distribuidas"] == 2
    # nenhuma senha aparece no metadata (defesa em profundidade)
    meta_dump = str(entry.meta)
    assert all(s not in meta_dump for s in senhas)

"""Integration tests do import de colaboradores (Sprint 2 #5).

Cobre auth, preview (novos/atualizados/erros), idempotência, cifragem
real do nome/email em repouso, e auditoria.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.models.operacional import Auditoria, ColaboradorImport
from app.services import auth_service

PREVIEW = "/v1/colaboradores/import/preview"
COMMIT = "/v1/colaboradores/import/commit"
COOKIE = "hcpa_admin_sessao"
SENHA = "senha-forte-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {COOKIE: r.cookies[COOKIE]}


async def _cc(db: AsyncSession, codigo: str, *, total: int = 10) -> CentroCusto:
    cc = CentroCusto(
        codigo=codigo,
        nome=f"CC {codigo}",
        total_colaboradores=total,
        bloco_predio="Bloco A",
    )
    db.add(cc)
    await db.flush()
    return cc


async def test_preview_exige_auth(client: AsyncClient) -> None:
    r = await client.post(
        PREVIEW,
        json={
            "itens": [
                {
                    "matricula": "M1",
                    "nome": "X",
                    "email": "x@example.com",
                    "centro_custo_codigo": "CC1",
                }
            ]
        },
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_ausente"


async def test_commit_exige_auth(client: AsyncClient) -> None:
    r = await client.post(
        COMMIT,
        json={
            "itens": [
                {
                    "matricula": "M1",
                    "nome": "X",
                    "email": "x@example.com",
                    "centro_custo_codigo": "CC1",
                }
            ]
        },
    )
    assert r.status_code == 401


async def test_preview_classifica_novos(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-prev1@example.com")
    codigo = f"CC-{uuid.uuid4().hex[:6]}"
    await _cc(db_session, codigo)
    payload = {
        "itens": [
            {
                "matricula": f"M-{uuid.uuid4().hex[:6]}",
                "nome": "Ana Silva",
                "email": "ana@example.com",
                "centro_custo_codigo": codigo,
            }
        ]
    }
    r = await client.post(PREVIEW, json=payload, cookies=cookies)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valido"] is True
    assert len(body["novos"]) == 1
    assert body["atualizados"] == []
    assert body["erros"] == []


async def test_preview_detecta_cc_inexistente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-prev2@example.com")
    payload = {
        "itens": [
            {
                "matricula": "M-ORF",
                "nome": "Órfão",
                "email": "orf@example.com",
                "centro_custo_codigo": "CC-NAO-EXISTE-XYZ",
            }
        ]
    }
    r = await client.post(PREVIEW, json=payload, cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["valido"] is False
    assert body["erros"][0]["matricula"] == "M-ORF"
    assert "não existe" in body["erros"][0]["erro"]


async def test_preview_detecta_matricula_duplicada(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-prev3@example.com")
    codigo = f"CC-{uuid.uuid4().hex[:6]}"
    await _cc(db_session, codigo)
    matricula = f"MDUP-{uuid.uuid4().hex[:6]}"
    payload = {
        "itens": [
            {
                "matricula": matricula,
                "nome": "A",
                "email": "a@example.com",
                "centro_custo_codigo": codigo,
            },
            {
                "matricula": matricula,
                "nome": "A2",
                "email": "a2@example.com",
                "centro_custo_codigo": codigo,
            },
        ]
    }
    r = await client.post(PREVIEW, json=payload, cookies=cookies)
    body = r.json()
    assert body["valido"] is False
    assert any("duplicada" in e["erro"] for e in body["erros"])


async def test_commit_persiste_pii_cifrada(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-com1@example.com")
    codigo = f"CC-{uuid.uuid4().hex[:6]}"
    await _cc(db_session, codigo)
    matricula = f"MAT-{uuid.uuid4().hex[:8]}"
    payload = {
        "itens": [
            {
                "matricula": matricula,
                "nome": "Bruno Costa",
                "email": "bruno@example.com",
                "centro_custo_codigo": codigo,
            }
        ]
    }
    r = await client.post(COMMIT, json=payload, cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json() == {"criados": 1, "atualizados": 0}

    col = (
        await db_session.execute(
            select(ColaboradorImport).where(ColaboradorImport.matricula == matricula)
        )
    ).scalar_one()
    assert col.nome == "Bruno Costa"
    assert col.email == "bruno@example.com"
    # ciphertext em repouso, não plaintext
    assert col.nome_enc is not None
    assert b"Bruno" not in bytes(col.nome_enc)
    assert col.senha_hash is None  # senha vem na fase de distribuição


async def test_commit_atualiza_pii_existente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-com2@example.com")
    codigo = f"CC-{uuid.uuid4().hex[:6]}"
    await _cc(db_session, codigo)
    matricula = f"MAT-{uuid.uuid4().hex[:8]}"

    base_payload = {
        "matricula": matricula,
        "nome": "Nome Antigo",
        "email": "antigo@example.com",
        "centro_custo_codigo": codigo,
    }
    r1 = await client.post(COMMIT, json={"itens": [base_payload]}, cookies=cookies)
    assert r1.status_code == 200

    novo_payload = {**base_payload, "nome": "Nome Novo", "email": "novo@example.com"}
    r2 = await client.post(COMMIT, json={"itens": [novo_payload]}, cookies=cookies)
    assert r2.json() == {"criados": 0, "atualizados": 1}

    col = (
        await db_session.execute(
            select(ColaboradorImport).where(ColaboradorImport.matricula == matricula)
        )
    ).scalar_one()
    assert col.nome == "Nome Novo"
    assert col.email == "novo@example.com"


async def test_commit_rejeita_payload_invalido(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="col-com3@example.com")
    payload = {
        "itens": [
            {
                "matricula": "Z1",
                "nome": "Z",
                "email": "z@example.com",
                "centro_custo_codigo": "CC-INEXISTENTE-YYY",
            }
        ]
    }
    r = await client.post(COMMIT, json=payload, cookies=cookies)
    assert r.status_code == 422
    assert r.json()["detail"]["erros"][0]["matricula"] == "Z1"


async def test_commit_registra_auditoria(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "col-audit@example.com"
    cookies = await _login(client, db_session, email=email)
    codigo = f"CC-{uuid.uuid4().hex[:6]}"
    await _cc(db_session, codigo)
    payload = {
        "itens": [
            {
                "matricula": f"AUD-{uuid.uuid4().hex[:6]}",
                "nome": "Auditado",
                "email": "aud@example.com",
                "centro_custo_codigo": codigo,
            }
        ]
    }
    await client.post(COMMIT, json=payload, cookies=cookies)
    entries = (
        (
            await db_session.execute(
                select(Auditoria).where(
                    Auditoria.acao == "colaboradores_import_commit",
                    Auditoria.usuario == email,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) >= 1
    assert entries[-1].meta["criados"] >= 1

"""Integration tests do descarte de colaborador_import (Sprint 2 #9).

Cenários:
- auth obrigatória
- `confirmar=false` ⇒ 422 (sem dropar a tabela)
- pendentes presentes ⇒ 409
- happy path ⇒ tabela vazia + credenciais intactas + auditoria registrada
- idempotência: rerun em tabela vazia ⇒ 0 descartados
- após descarte, login do respondente CONTINUA funcionando (credencial sobrevive)
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.models.operacional import Auditoria, ColaboradorImport, Credencial
from app.services import auth_service

COMMIT_COL = "/v1/colaboradores/import/commit"
DISTRIBUIR = "/v1/colaboradores/distribuir"
DESCARTAR = "/v1/colaboradores/descartar"
LOGIN_OP = "/v1/auth/login"
LOGIN_RESP = "/v1/auth/respondente"
COOKIE_OP = "hcpa_admin_sessao"
SENHA_OP = "senha-forte-op-1234"


async def _login_operador(
    client: AsyncClient, db: AsyncSession, *, email: str
) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA_OP)
    r = await client.post(LOGIN_OP, json={"email": email, "senha": SENHA_OP})
    assert r.status_code == 200
    return {COOKIE_OP: r.cookies[COOKIE_OP]}


async def _pipeline_distribuido(
    client: AsyncClient, db: AsyncSession, *, email_op: str
) -> tuple[dict[str, str], list[dict[str, str]]]:
    cookies = await _login_operador(client, db, email=email_op)
    codigo = f"CC-DESC-{uuid.uuid4().hex[:6]}"
    cc = CentroCusto(codigo=codigo, nome=codigo, total_colaboradores=10)
    db.add(cc)
    await db.flush()

    matriculas = [f"DESC-{uuid.uuid4().hex[:6]}" for _ in range(2)]
    await client.post(
        COMMIT_COL,
        json={
            "itens": [
                {
                    "matricula": m,
                    "nome": f"Pessoa {i}",
                    "email": f"{m.lower()}@example.com",
                    "centro_custo_codigo": codigo,
                }
                for i, m in enumerate(matriculas)
            ]
        },
        cookies=cookies,
    )
    r = await client.post(DISTRIBUIR, cookies=cookies)
    return cookies, r.json()["credenciais"]


async def test_descartar_exige_auth(client: AsyncClient) -> None:
    r = await client.post(DESCARTAR, json={"confirmar": True})
    assert r.status_code == 401


async def test_descartar_sem_confirmar_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login_operador(client, db_session, email="dc1@example.com")
    r = await client.post(DESCARTAR, json={"confirmar": False}, cookies=cookies)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "descarte_nao_confirmado"


async def test_descartar_falha_se_ha_pendentes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Cria colaborador mas NÃO chama /distribuir — fica pendente."""
    cookies = await _login_operador(client, db_session, email="dc2@example.com")
    codigo = f"CC-PEND-{uuid.uuid4().hex[:6]}"
    cc = CentroCusto(codigo=codigo, nome=codigo, total_colaboradores=10)
    db_session.add(cc)
    await db_session.flush()
    await client.post(
        COMMIT_COL,
        json={
            "itens": [
                {
                    "matricula": f"P-{uuid.uuid4().hex[:6]}",
                    "nome": "X",
                    "email": "x@example.com",
                    "centro_custo_codigo": codigo,
                }
            ]
        },
        cookies=cookies,
    )
    r = await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "descarte_com_pendentes"


async def test_descartar_happy_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies, _creds = await _pipeline_distribuido(
        client, db_session, email_op="dc3@example.com"
    )

    # confere quantos colaboradores existem antes do descarte
    n_antes = (
        await db_session.execute(select(func.count(ColaboradorImport.matricula)))
    ).scalar_one()
    n_creds_antes = (
        await db_session.execute(select(func.count(Credencial.senha_hash)))
    ).scalar_one()
    assert n_antes >= 2

    r = await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["descartados"] == n_antes

    # tabela colaborador_import zerada
    assert (
        (
            await db_session.execute(select(func.count(ColaboradorImport.matricula)))
        ).scalar_one()
        == 0
    )
    # credencial NÃO foi tocada
    n_creds_depois = (
        await db_session.execute(select(func.count(Credencial.senha_hash)))
    ).scalar_one()
    assert n_creds_depois == n_creds_antes


async def test_descartar_e_idempotente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies, _ = await _pipeline_distribuido(
        client, db_session, email_op="dc4@example.com"
    )
    r1 = await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)
    assert r1.status_code == 200
    assert r1.json()["descartados"] >= 1
    r2 = await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)
    assert r2.status_code == 200
    assert r2.json()["descartados"] == 0


async def test_login_respondente_funciona_apos_descarte(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """O invariante chave: credenciais sobrevivem ao descarte de identidade."""
    cookies, creds = await _pipeline_distribuido(
        client, db_session, email_op="dc5@example.com"
    )
    senha = creds[0]["senha"]
    await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)

    r = await client.post(LOGIN_RESP, json={"senha": senha})
    assert r.status_code == 200, r.text
    assert "token_sessao" in r.json()


async def test_descarte_registra_auditoria(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "dc-audit@example.com"
    cookies, _ = await _pipeline_distribuido(
        client, db_session, email_op=email
    )
    r = await client.post(DESCARTAR, json={"confirmar": True}, cookies=cookies)
    assert r.status_code == 200

    entries = (
        (
            await db_session.execute(
                select(Auditoria).where(
                    Auditoria.acao == "colaborador_import_descartado",
                    Auditoria.usuario == email,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) >= 1
    assert entries[-1].meta["descartados"] >= 1

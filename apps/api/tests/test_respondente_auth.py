"""Integration tests da autenticação do respondente (Sprint 2 #7)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.models.operacional import Credencial
from app.services import auth_service

LOGIN_OP = "/v1/auth/login"
COMMIT_COL = "/v1/colaboradores/import/commit"
DISTRIBUIR = "/v1/colaboradores/distribuir"
LOGIN_RESP = "/v1/auth/respondente"
COOKIE_OP = "hcpa_admin_sessao"
COOKIE_RESP = "hcpa_resp_sessao"
SENHA_OP = "senha-forte-op-1234"


async def _login_operador(
    client: AsyncClient, db: AsyncSession, *, email: str
) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA_OP)
    r = await client.post(LOGIN_OP, json={"email": email, "senha": SENHA_OP})
    assert r.status_code == 200
    return {COOKIE_OP: r.cookies[COOKIE_OP]}


async def _pipeline_distribuir_uma(
    client: AsyncClient, db: AsyncSession, *, email: str
) -> str:
    """Roda CC + colaborador + distribuir → devolve uma senha em texto claro."""
    cookies = await _login_operador(client, db, email=email)
    codigo = f"CC-RESP-{uuid.uuid4().hex[:6]}"
    cc = CentroCusto(codigo=codigo, nome=codigo, total_colaboradores=10)
    db.add(cc)
    await db.flush()

    matricula = f"RESP-{uuid.uuid4().hex[:6]}"
    await client.post(
        COMMIT_COL,
        json={
            "itens": [
                {
                    "matricula": matricula,
                    "nome": "Resp Teste",
                    "email": "resp@example.com",
                    "centro_custo_codigo": codigo,
                }
            ]
        },
        cookies=cookies,
    )
    r = await client.post(DISTRIBUIR, cookies=cookies)
    creds = r.json()["credenciais"]
    return next(c["senha"] for c in creds if c["matricula"] == matricula)


async def test_senha_correta_emite_cookie_e_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    senha = await _pipeline_distribuir_uma(client, db_session, email="r1@example.com")
    r = await client.post(LOGIN_RESP, json={"senha": senha})
    assert r.status_code == 200, r.text
    body = r.json()
    assert uuid.UUID(body["token_sessao"])
    assert COOKIE_RESP in r.cookies
    assert r.cookies[COOKIE_RESP] == body["token_sessao"]


async def test_senha_incorreta_devolve_404_senha_invalida(
    client: AsyncClient,
) -> None:
    r = await client.post(LOGIN_RESP, json={"senha": "definitivamente-errada-XYZ"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "senha_invalida"


async def test_login_e_idempotente_dentro_da_janela(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    senha = await _pipeline_distribuir_uma(client, db_session, email="r2@example.com")
    r1 = await client.post(LOGIN_RESP, json={"senha": senha})
    r2 = await client.post(LOGIN_RESP, json={"senha": senha})
    assert r1.json()["token_sessao"] == r2.json()["token_sessao"]


async def test_sessao_expirada_emite_novo_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    senha = await _pipeline_distribuir_uma(client, db_session, email="r3@example.com")
    r1 = await client.post(LOGIN_RESP, json={"senha": senha})
    token1 = r1.json()["token_sessao"]

    # força expiração via update direto
    cred = (
        await db_session.execute(
            select(Credencial).where(
                Credencial.token_sessao_temporario == uuid.UUID(token1)
            )
        )
    ).scalar_one()
    cred.expira_em = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.flush()
    await db_session.commit()

    r2 = await client.post(LOGIN_RESP, json={"senha": senha})
    assert r2.status_code == 200
    assert r2.json()["token_sessao"] != token1


async def test_payload_invalido_devolve_422(client: AsyncClient) -> None:
    r = await client.post(LOGIN_RESP, json={})
    assert r.status_code == 422

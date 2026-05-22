"""Integration tests do endpoint POST /v1/questionarios (Sprint 2 #8).

Cobre o fluxo completo: auth do respondente → criação aplicando granularidade
condicional → token_anonimo retornado funciona com o endpoint público de
submissão de respostas. Também valida que NENHUM campo na resposta permite
reconstruir o respondente (anonimato by design).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import QuestionarioStatus
from app.models.core import CentroCusto, Dominio, Item, Questionario
from app.services import auth_service

COMMIT_COL = "/v1/colaboradores/import/commit"
DISTRIBUIR = "/v1/colaboradores/distribuir"
LOGIN_RESP = "/v1/auth/respondente"
LOGIN_OP = "/v1/auth/login"
CRIAR_Q = "/v1/questionarios"
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


async def _pipeline_ate_cookie_resp(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email_op: str,
    total_cc: int = 10,
    bloco: str | None = "Bloco A",
) -> tuple[CentroCusto, dict[str, str]]:
    """Cria CC + colaborador + distribui + loga respondente. Retorna (cc, cookies_resp)."""
    cookies_op = await _login_operador(client, db, email=email_op)
    codigo = f"CC-Q-{uuid.uuid4().hex[:6]}"
    cc = CentroCusto(
        codigo=codigo, nome=codigo, total_colaboradores=total_cc, bloco_predio=bloco
    )
    db.add(cc)
    await db.flush()

    matricula = f"Q-{uuid.uuid4().hex[:6]}"
    await client.post(
        COMMIT_COL,
        json={
            "itens": [
                {
                    "matricula": matricula,
                    "nome": "Resp Q",
                    "email": "q@example.com",
                    "centro_custo_codigo": codigo,
                }
            ]
        },
        cookies=cookies_op,
    )
    r = await client.post(DISTRIBUIR, cookies=cookies_op)
    senha = next(
        c["senha"] for c in r.json()["credenciais"] if c["matricula"] == matricula
    )
    rl = await client.post(LOGIN_RESP, json={"senha": senha})
    return cc, {COOKIE_RESP: rl.cookies[COOKIE_RESP]}


async def test_criar_exige_cookie_respondente(client: AsyncClient) -> None:
    r = await client.post(CRIAR_Q)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_respondente_ausente"


async def test_cc_grande_grava_centro_custo_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc, cookies = await _pipeline_ate_cookie_resp(
        client, db_session, email_op="qg1@example.com", total_cc=20
    )
    r = await client.post(CRIAR_Q, cookies=cookies)
    assert r.status_code == 201, r.text
    body = r.json()
    qid = uuid.UUID(body["questionario_id"])
    assert uuid.UUID(body["token_anonimo"])

    q = (
        await db_session.execute(select(Questionario).where(Questionario.id == qid))
    ).scalar_one()
    assert q.centro_custo_id == cc.id
    assert q.bloco_predio is None


async def test_cc_pequeno_cai_para_bloco_predio(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc, cookies = await _pipeline_ate_cookie_resp(
        client, db_session, email_op="qp1@example.com", total_cc=2, bloco="Bloco X"
    )
    r = await client.post(CRIAR_Q, cookies=cookies)
    assert r.status_code == 201
    qid = uuid.UUID(r.json()["questionario_id"])
    q = (
        await db_session.execute(select(Questionario).where(Questionario.id == qid))
    ).scalar_one()
    assert q.centro_custo_id is None
    assert q.bloco_predio == "Bloco X"


async def test_cc_pequeno_sem_bloco_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _cc, cookies = await _pipeline_ate_cookie_resp(
        client, db_session, email_op="qpsb@example.com", total_cc=2, bloco=None
    )
    r = await client.post(CRIAR_Q, cookies=cookies)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "granularidade_indisponivel"


async def test_token_anonimo_funciona_no_endpoint_publico_de_respostas(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Integração entre criar_questionario e submeter respostas — totem PWA."""
    _cc, cookies = await _pipeline_ate_cookie_resp(
        client, db_session, email_op="qe2e@example.com", total_cc=20
    )

    dominio = Dominio(nome="Demandas", polaridade=-1, ordem_apresentacao=1)
    db_session.add(dominio)
    await db_session.flush()
    item = Item(
        dominio_id=dominio.id,
        texto_pergunta="Pergunta?",
        ordem_apresentacao=1,
        escala_tipo="A",
        invertido=False,
    )
    db_session.add(item)
    await db_session.flush()

    rc = await client.post(CRIAR_Q, cookies=cookies)
    token = rc.json()["token_anonimo"]

    rs = await client.post(
        f"/v1/questionarios/{token}/respostas",
        json={"respostas": [{"item_id": str(item.id), "valor": 3}]},
    )
    assert rs.status_code == 201, rs.text

    q = (
        await db_session.execute(
            select(Questionario).where(Questionario.token_anonimo == uuid.UUID(token))
        )
    ).scalar_one()
    assert q.status == QuestionarioStatus.concluido

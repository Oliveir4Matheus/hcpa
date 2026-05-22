"""Spec compliance — Pipeline E2E declarado na documentação do projeto.

Roadmap (README §Roadmap) e princípio "Anonimato by design":

    Operador HMind:
      1. cria operador (CLI) + login + (opcional) TOTP
      2. POST /v1/centros-custo/import/{preview,commit}
      3. POST /v1/colaboradores/import/{preview,commit}
      4. POST /v1/colaboradores/distribuir       → recebe senhas em texto claro
      5. (entrega física aos colaboradores)
      6. POST /v1/colaboradores/descartar         → zera colaborador_import

    Respondente (totem PWA):
      A. POST /v1/auth/respondente               → cookie hcpa_resp_sessao
      B. POST /v1/questionarios                  → recebe token_anonimo
      C. POST /v1/questionarios/{token}/respostas  (público)

    Operador, depois:
      D. GET  /v1/respostas/agregado?centro_custo_id=...

Este módulo testa **o pipeline inteiro em uma única passagem**. Se algum
passo quebrar a contratualidade do próximo, este teste captura.

Invariantes específicos validados aqui (cruzando camadas):
- A senha em texto claro do passo 4 LOGA no passo A.
- O `token_anonimo` do passo B liga ao centro_custo correto via gravação no
  Questionario (granularidade condicional).
- Após o passo 6 (descarte), o passo A ainda funciona (credenciais sobrevivem).
- O agregado do passo D vê as respostas e respeita k-anonimato.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import QuestionarioStatus, StatusDistribuicao
from app.models.core import Dominio, Item, Questionario
from app.models.operacional import ColaboradorImport, Credencial
from app.services import auth_service

COOKIE_OP = "hcpa_admin_sessao"
COOKIE_RESP = "hcpa_resp_sessao"
SENHA_OP = "senha-forte-1234"


class TestPipelineCompletoE2E:
    """Um único método grande que sequencia todos os passos da Sprint 2.

    Mantido em UM método pelo determinismo de pipeline: cada passo depende
    do estado deixado pelo anterior. Quebrar em métodos separados forçaria
    re-seed e perderia o sentido de "smoke E2E em memória".
    """

    async def test_pipeline_inteiro_funciona_e_preserva_invariantes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # --- passo 1: bootstrap operador + login -----------------------------
        op_email = f"e2e-op-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=op_email, senha=SENHA_OP)
        r = await client.post(
            "/v1/auth/login", json={"email": op_email, "senha": SENHA_OP}
        )
        assert r.status_code == 200
        op_cookies = {COOKIE_OP: r.cookies[COOKIE_OP]}

        # --- passo 2: importar centro de custo (>=5 para gravar centro_custo_id)
        cc_codigo_grande = f"CC-E2E-G-{uuid.uuid4().hex[:6]}"
        cc_codigo_pequeno = f"CC-E2E-P-{uuid.uuid4().hex[:6]}"
        r = await client.post(
            "/v1/centros-custo/import/commit",
            json={
                "itens": [
                    {
                        "codigo": cc_codigo_grande,
                        "nome": "Setor Grande",
                        "total_colaboradores": 20,
                        "bloco_predio": "Bloco A",
                    },
                    {
                        "codigo": cc_codigo_pequeno,
                        "nome": "Setor Pequeno",
                        "total_colaboradores": 2,
                        "bloco_predio": "Bloco P",
                    },
                ]
            },
            cookies=op_cookies,
        )
        assert r.status_code == 200, r.text

        # --- passo 3: importar colaboradores ---------------------------------
        matriculas_grande = [f"GRA-{uuid.uuid4().hex[:6]}" for _ in range(6)]
        matricula_pequena = f"PEQ-{uuid.uuid4().hex[:6]}"
        r = await client.post(
            "/v1/colaboradores/import/commit",
            json={
                "itens": [
                    {
                        "matricula": m,
                        "nome": f"Pessoa {i}",
                        "email": f"{m.lower()}@example.com",
                        "centro_custo_codigo": cc_codigo_grande,
                    }
                    for i, m in enumerate(matriculas_grande)
                ]
                + [
                    {
                        "matricula": matricula_pequena,
                        "nome": "Pequena",
                        "email": "peq@example.com",
                        "centro_custo_codigo": cc_codigo_pequeno,
                    }
                ]
            },
            cookies=op_cookies,
        )
        assert r.status_code == 200

        # --- passo 4: distribuir credenciais ---------------------------------
        r = await client.post("/v1/colaboradores/distribuir", cookies=op_cookies)
        assert r.status_code == 200
        body = r.json()
        assert body["distribuidas"] == 7
        senha_por_matricula = {c["matricula"]: c["senha"] for c in body["credenciais"]}

        # CONTRATO 1: todas as senhas são distintas (alta entropia).
        assert len(set(senha_por_matricula.values())) == 7
        # CONTRATO 2: status_distribuicao virou `distribuida`.
        cols = (
            (await db_session.execute(select(ColaboradorImport))).scalars().all()
        )
        assert all(c.status_distribuicao == StatusDistribuicao.distribuida for c in cols)

        # --- passo A: respondente do CC grande loga --------------------------
        senha_grande_0 = senha_por_matricula[matriculas_grande[0]]
        r = await client.post(
            "/v1/auth/respondente", json={"senha": senha_grande_0}
        )
        assert r.status_code == 200
        resp_cookies_grande = {COOKIE_RESP: r.cookies[COOKIE_RESP]}

        # --- passo B: cria questionário do respondente grande ---------------
        r = await client.post("/v1/questionarios", cookies=resp_cookies_grande)
        assert r.status_code == 201
        token_grande = r.json()["token_anonimo"]
        q_grande = (
            await db_session.execute(
                select(Questionario).where(
                    Questionario.token_anonimo == uuid.UUID(token_grande)
                )
            )
        ).scalar_one()
        # CONTRATO 3: CC grande grava centro_custo_id, NÃO bloco.
        assert q_grande.centro_custo_id is not None
        assert q_grande.bloco_predio is None

        # --- mesmo passo para os outros 4 respondentes do CC grande ---------
        for matricula in matriculas_grande[1:5]:
            r = await client.post(
                "/v1/auth/respondente",
                json={"senha": senha_por_matricula[matricula]},
            )
            r_cookies = {COOKIE_RESP: r.cookies[COOKIE_RESP]}
            await client.post("/v1/questionarios", cookies=r_cookies)

        # --- respondente do CC pequeno ---------------------------------------
        r = await client.post(
            "/v1/auth/respondente",
            json={"senha": senha_por_matricula[matricula_pequena]},
        )
        resp_cookies_pequeno = {COOKIE_RESP: r.cookies[COOKIE_RESP]}
        r = await client.post("/v1/questionarios", cookies=resp_cookies_pequeno)
        assert r.status_code == 201
        token_pequeno = r.json()["token_anonimo"]
        q_pequeno = (
            await db_session.execute(
                select(Questionario).where(
                    Questionario.token_anonimo == uuid.UUID(token_pequeno)
                )
            )
        ).scalar_one()
        # CONTRATO 4: CC pequeno grava bloco, NÃO centro_custo_id.
        assert q_pequeno.centro_custo_id is None
        assert q_pequeno.bloco_predio == "Bloco P"

        # --- passo C: submissão pública (sem cookie) ------------------------
        d = Dominio(nome=f"D-E2E-{uuid.uuid4().hex[:6]}", polaridade=-1, ordem_apresentacao=1)
        db_session.add(d)
        await db_session.flush()
        it = Item(
            dominio_id=d.id,
            texto_pergunta="?",
            ordem_apresentacao=1,
            escala_tipo="A",
            invertido=False,
        )
        db_session.add(it)
        await db_session.flush()

        # Submete para 5 questionários do CC grande (5 = K_ANONIMATO_MIN).
        for _ in range(5):
            # pega um questionário em estado `iniciado` no CC grande
            q_para_submeter = (
                await db_session.execute(
                    select(Questionario).where(
                        Questionario.centro_custo_id == q_grande.centro_custo_id,
                        Questionario.status == QuestionarioStatus.iniciado,
                    )
                )
            ).scalars().first()
            assert q_para_submeter is not None
            r = await client.post(
                f"/v1/questionarios/{q_para_submeter.token_anonimo}/respostas",
                json={"respostas": [{"item_id": str(it.id), "valor": 2}]},
            )
            assert r.status_code == 201
            await db_session.refresh(q_para_submeter)

        # --- passo D: operador agrega ---------------------------------------
        r = await client.get(
            "/v1/respostas/agregado",
            params={"centro_custo_id": str(q_grande.centro_custo_id)},
            cookies=op_cookies,
        )
        assert r.status_code == 200
        agg = r.json()
        # CONTRATO 5: limiar de 5 questionários liberou agregação.
        assert agg["supressao"] is None
        assert agg["n_questionarios"] == 5

        # --- passo 6: descartar colaborador_import --------------------------
        r = await client.post(
            "/v1/colaboradores/descartar",
            json={"confirmar": True},
            cookies=op_cookies,
        )
        assert r.status_code == 200
        assert r.json()["descartados"] == 7

        # CONTRATO 6: colaborador_import zerada, credencial intacta.
        assert (
            (
                await db_session.execute(
                    select(func.count(ColaboradorImport.matricula))
                )
            ).scalar_one()
            == 0
        )
        n_credenciais = (
            await db_session.execute(select(func.count(Credencial.senha_hash)))
        ).scalar_one()
        assert n_credenciais == 7

        # CONTRATO 7: respondente ainda consegue logar com sua senha após descarte.
        # (credencial é a fonte de verdade pós-descarte)
        r = await client.post(
            "/v1/auth/respondente",
            json={"senha": senha_por_matricula[matriculas_grande[5]]},
        )
        assert r.status_code == 200

        # CONTRATO 8: agregado continua acessível depois do descarte.
        r = await client.get(
            "/v1/respostas/agregado",
            params={"centro_custo_id": str(q_grande.centro_custo_id)},
            cookies=op_cookies,
        )
        assert r.status_code == 200
        assert r.json()["n_questionarios"] == 5

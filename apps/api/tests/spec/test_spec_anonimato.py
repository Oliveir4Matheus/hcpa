"""Spec compliance — "Anonimato by design" (README §Princípios + §5/§6 doc técnica v1).

> identidade só serve para liberar acesso; tabela `colaborador_import` é
> descartada após a distribuição de senhas. Caminho de query a partir de
> uma resposta termina sem identidade: respostas → questionarios →
> centros_custo. Nenhuma FK alcança colaborador_import.

Os testes deste módulo NÃO verificam features individuais — verificam
invariantes arquiteturais que precisam continuar valendo independente de
quais endpoints existem ou são adicionados.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto, Item, Questionario, Resposta
from app.models.operacional import ColaboradorImport, Credencial, Lembrete
from app.schemas.resposta import RespostaIn
from app.services.questionario_service import criar_questionario
from app.services.resposta_service import submeter_respostas


# ---------------------------------------------------------------------------
# Invariante A1 — Nenhuma FK em `respostas`/`questionarios` alcança identidade
# ---------------------------------------------------------------------------


class TestFKsNaoAlcancamIdentidade:
    """Caminho de query a partir de uma resposta deve terminar sem identidade.

    Inspeciona o metadata SQLAlchemy diretamente: se alguém adicionar uma FK
    de `respostas` ou `questionarios` para `colaborador_import` (ou para
    qualquer tabela de PII), este teste quebra antes do código chegar em prod.
    """

    TABELAS_PROIBIDAS = {"colaborador_import", "credencial", "operadores"}

    def test_resposta_nao_referencia_tabela_de_identidade(self) -> None:
        for fk in Resposta.__table__.foreign_keys:
            referenciada = fk.column.table.name
            assert referenciada not in self.TABELAS_PROIBIDAS, (
                f"Resposta tem FK para {referenciada}, violando anonimato by design."
            )

    def test_questionario_nao_referencia_tabela_de_identidade(self) -> None:
        for fk in Questionario.__table__.foreign_keys:
            referenciada = fk.column.table.name
            assert referenciada not in self.TABELAS_PROIBIDAS

    def test_credencial_nao_referencia_colaborador_import(self) -> None:
        """`credencial` precisa ser independente de `colaborador_import` para
        sobreviver ao descarte (Sprint 2 #9)."""
        for fk in Credencial.__table__.foreign_keys:
            assert fk.column.table.name != "colaborador_import"

    def test_lembrete_nao_tem_fk_para_colaborador_import(self) -> None:
        """A FK foi removida na migration 4d8f1e6c9b33 para preservar
        histórico de engajamento após o descarte."""
        for fk in Lembrete.__table__.foreign_keys:
            assert fk.column.table.name != "colaborador_import"


# ---------------------------------------------------------------------------
# Invariante A2 — Relationships ORM também não tocam identidade
# ---------------------------------------------------------------------------


class TestRelationshipsORMSemIdentidade:
    """SQLAlchemy permite navegar via `relationship()` sem FK explícita.
    Garante que nenhum `Resposta.X` ou `Questionario.X` resolve para
    `ColaboradorImport` mesmo via relationship."""

    def test_resposta_relationships_nao_alcancam_colaborador_import(self) -> None:
        mapper = inspect(Resposta)
        for rel in mapper.relationships:
            assert rel.mapper.class_ is not ColaboradorImport, (
                f"Resposta.{rel.key} aponta para ColaboradorImport — proibido."
            )

    def test_questionario_relationships_nao_alcancam_colaborador_import(self) -> None:
        mapper = inspect(Questionario)
        for rel in mapper.relationships:
            assert rel.mapper.class_ is not ColaboradorImport


# ---------------------------------------------------------------------------
# Invariante A3 — Token anônimo é descorrelacionado da identidade
# ---------------------------------------------------------------------------


class TestTokenAnonimo:
    """`token_anonimo` é UUID gerado pelo banco (`gen_random_uuid()`) e
    nunca derivado do respondente."""

    def test_coluna_e_unique_no_schema(self) -> None:
        col = Questionario.__table__.c["token_anonimo"]
        assert col.unique is True
        assert col.nullable is False

    def test_default_e_gen_random_uuid(self) -> None:
        col = Questionario.__table__.c["token_anonimo"]
        default_sql = str(col.server_default.arg)
        assert "gen_random_uuid" in default_sql

    async def test_tokens_de_dois_questionarios_diferem(
        self, db_session: AsyncSession
    ) -> None:
        cc = CentroCusto(
            codigo=f"CC-TOK-{uuid.uuid4().hex[:6]}", nome="X", total_colaboradores=10
        )
        db_session.add(cc)
        await db_session.flush()
        q1 = await criar_questionario(db_session, centro_custo=cc)
        q2 = await criar_questionario(db_session, centro_custo=cc)
        assert q1.token_anonimo != q2.token_anonimo


# ---------------------------------------------------------------------------
# Invariante A4 — Timing-correlação suavizada
# ---------------------------------------------------------------------------


class TestTimingCorrelacaoSuavizada:
    """submetida_em e data_conclusao gravadas com granularidade de HORA
    para mitigar correlação cronológica entre respondentes e clientes
    externos que observem timing.

    Spec: docstring de `resposta_service._agora_em_hora` + comentário em
    `models/core.py:Resposta.submetida_em`.
    """

    async def _cc_com_resposta(
        self, client: AsyncClient, db: AsyncSession
    ) -> Resposta:
        from app.models.core import Dominio

        cc = CentroCusto(
            codigo=f"CC-TIM-{uuid.uuid4().hex[:6]}", nome="X", total_colaboradores=10
        )
        db.add(cc)
        await db.flush()
        d = Dominio(nome="D", polaridade=-1, ordem_apresentacao=1)
        db.add(d)
        await db.flush()
        item = Item(
            dominio_id=d.id,
            texto_pergunta="?",
            ordem_apresentacao=1,
            escala_tipo="A",
            invertido=False,
        )
        db.add(item)
        await db.flush()
        q = await criar_questionario(db, centro_custo=cc)
        await submeter_respostas(
            db,
            token_anonimo=q.token_anonimo,
            respostas=[RespostaIn(item_id=item.id, valor=2)],
        )
        r = (
            await db.execute(select(Resposta).where(Resposta.questionario_id == q.id))
        ).scalar_one()
        return r

    async def test_submetida_em_arredonda_para_hora(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        r = await self._cc_com_resposta(client, db_session)
        assert r.submetida_em.minute == 0
        assert r.submetida_em.second == 0
        assert r.submetida_em.microsecond == 0

    async def test_data_conclusao_arredonda_para_hora(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        r = await self._cc_com_resposta(client, db_session)
        q = (
            await db_session.execute(
                select(Questionario).where(Questionario.id == r.questionario_id)
            )
        ).scalar_one()
        assert q.data_conclusao is not None
        assert q.data_conclusao.minute == 0
        assert q.data_conclusao.second == 0


# ---------------------------------------------------------------------------
# Invariante A5 — Submissão pública não exige autenticação
# ---------------------------------------------------------------------------


class TestSubmissaoPublicaSemAuth:
    """O respondente é identificado APENAS pelo `token_anonimo` na URL.
    Exigir cookie ou JWT seria uma forma de correlacionar identidade →
    questionário, violando o princípio."""

    async def test_post_respostas_aceito_sem_cookie(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from app.models.core import Dominio

        cc = CentroCusto(
            codigo=f"CC-PUB-{uuid.uuid4().hex[:6]}",
            nome="X",
            total_colaboradores=20,
        )
        db_session.add(cc)
        await db_session.flush()
        d = Dominio(nome="D", polaridade=-1, ordem_apresentacao=1)
        db_session.add(d)
        await db_session.flush()
        item = Item(
            dominio_id=d.id,
            texto_pergunta="?",
            ordem_apresentacao=1,
            escala_tipo="A",
            invertido=False,
        )
        db_session.add(item)
        await db_session.flush()
        q = await criar_questionario(db_session, centro_custo=cc)

        # Cliente SEM qualquer cookie de sessão.
        r = await client.post(
            f"/v1/questionarios/{q.token_anonimo}/respostas",
            json={"respostas": [{"item_id": str(item.id), "valor": 2}]},
        )
        assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# Invariante A6 — Cookies de respondente e operador são distintos
# ---------------------------------------------------------------------------


class TestCookiesSegregados:
    """Misturar os cookies permitiria escalonamento de privilégio entre
    operador (acesso ao painel) e respondente (apenas submissão)."""

    def test_cookies_tem_nomes_diferentes(self) -> None:
        from app.api.v1.auth import COOKIE_NOME as COOKIE_OPERADOR
        from app.api.v1.auth_respondente import COOKIE_RESPONDENTE

        assert COOKIE_OPERADOR != COOKIE_RESPONDENTE
        # nomes prefixados para facilitar inspeção do operador via devtools
        assert COOKIE_OPERADOR == "hcpa_admin_sessao"
        assert COOKIE_RESPONDENTE == "hcpa_resp_sessao"


# ---------------------------------------------------------------------------
# Invariante A7 — Descarte preserva a capacidade de coletar/agregar respostas
# ---------------------------------------------------------------------------


class TestDescarteNaoQuebrarRespostas:
    """O descarte da identidade (`colaborador_import`) NÃO pode invalidar
    questionários/respostas já coletadas — caso contrário, descartar a
    PII inviabilizaria o objetivo do projeto (laudo agregado)."""

    def test_questionario_nao_tem_fk_para_colaborador_import(self) -> None:
        # Repete A1 sob outro ângulo: se o descarte tivesse efeito CASCADE
        # nas respostas, este invariante quebraria.
        for fk in Questionario.__table__.foreign_keys:
            assert fk.column.table.name != "colaborador_import"

    def test_resposta_cascade_so_e_sobre_questionario(self) -> None:
        """A única CASCADE em `respostas` é a partir de questionario —
        deletar uma identidade NÃO derruba respostas (porque não há FK)."""
        for fk in Resposta.__table__.foreign_keys:
            if fk.column.table.name == "questionarios":
                assert fk.ondelete == "CASCADE"
            else:
                # itens e dominios usam RESTRICT — não deletam respostas
                assert fk.ondelete == "RESTRICT"


# ---------------------------------------------------------------------------
# Invariante A8 — Submissão NÃO grava usuário identificável na auditoria
# ---------------------------------------------------------------------------


class TestAuditoriaDeSubmissaoEAnonima:
    """A trilha de auditoria deve registrar a ação para fins de contagem
    mas NÃO pode anotar identidade — caso contrário, cruza com o questionario."""

    async def test_auditoria_de_submissao_usa_usuario_generico(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from app.models.core import Dominio
        from app.models.operacional import Auditoria

        cc = CentroCusto(
            codigo=f"CC-AUD-{uuid.uuid4().hex[:6]}", nome="X", total_colaboradores=10
        )
        db_session.add(cc)
        await db_session.flush()
        d = Dominio(nome="D", polaridade=-1, ordem_apresentacao=1)
        db_session.add(d)
        await db_session.flush()
        item = Item(
            dominio_id=d.id,
            texto_pergunta="?",
            ordem_apresentacao=1,
            escala_tipo="A",
            invertido=False,
        )
        db_session.add(item)
        await db_session.flush()
        q = await criar_questionario(db_session, centro_custo=cc)
        await client.post(
            f"/v1/questionarios/{q.token_anonimo}/respostas",
            json={"respostas": [{"item_id": str(item.id), "valor": 2}]},
        )

        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.acao == "respostas_submetidas",
                        Auditoria.meta["questionario_id"].astext == str(q.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1
        # usuario deve ser literal "anonimo" — não email, não matrícula.
        assert entries[-1].usuario == "anonimo"


# ---------------------------------------------------------------------------
# Invariante A9 — Submetida_em sempre em UTC (defesa adicional contra timing)
# ---------------------------------------------------------------------------


class TestTimestampsEmUTC:
    """Timezone consistente evita que o fuso revele o local do respondente."""

    async def test_submetida_em_tem_tzinfo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from app.models.core import Dominio

        cc = CentroCusto(
            codigo=f"CC-UTC-{uuid.uuid4().hex[:6]}", nome="X", total_colaboradores=10
        )
        db_session.add(cc)
        await db_session.flush()
        d = Dominio(nome="D", polaridade=-1, ordem_apresentacao=1)
        db_session.add(d)
        await db_session.flush()
        item = Item(
            dominio_id=d.id,
            texto_pergunta="?",
            ordem_apresentacao=1,
            escala_tipo="A",
            invertido=False,
        )
        db_session.add(item)
        await db_session.flush()
        q = await criar_questionario(db_session, centro_custo=cc)
        await submeter_respostas(
            db_session,
            token_anonimo=q.token_anonimo,
            respostas=[RespostaIn(item_id=item.id, valor=1)],
        )
        r = (
            await db_session.execute(
                select(Resposta).where(Resposta.questionario_id == q.id)
            )
        ).scalar_one()
        assert r.submetida_em.tzinfo is not None

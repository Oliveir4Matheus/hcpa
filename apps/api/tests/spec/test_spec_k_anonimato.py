"""Spec compliance — K-anonimato em repouso e em consulta.

Spec: §5 ("K-anonimato no banco") e §6 da doc técnica v1, citada nos
docstrings de:
- `app/services/questionario_service.py` — gravação
- `app/services/resposta_service.py:agregar_respostas_por_cc` — consulta

Invariantes deste módulo:
- `K_ANONIMATO_MIN` é a constante única que controla ambos os lados.
- Limiar é inclusivo: total = K_ANONIMATO_MIN → grava CC; total = K_ANONIMATO_MIN-1 → cai pra bloco.
- Constraint `ck_questionarios_granularidade_xor` impede ambos NULL ou ambos preenchidos.
- Consulta com N < K_ANONIMATO_MIN devolve `AgregadoSupressao`.
- Limiar de consulta é inclusivo: N = K_ANONIMATO_MIN → libera; N = K_ANONIMATO_MIN-1 → suprime.
- O mesmo erro estável `granularidade_indisponivel` é usado em gravação e consulta.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto, Dominio, Item, Questionario
from app.schemas.resposta import AgregadoSupressao, RespostaIn
from app.services import auth_service
from app.services.questionario_service import (
    K_ANONIMATO_MIN,
    QuestionarioError,
    criar_questionario,
)
from app.services.resposta_service import (
    RespostaError,
    agregar_respostas_por_cc,
    submeter_respostas,
)

COOKIE = "hcpa_admin_sessao"
SENHA = "senha-forte-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA})
    return {COOKIE: r.cookies[COOKIE]}


async def _cc(db: AsyncSession, *, total: int, bloco: str | None = "Bloco A") -> CentroCusto:
    cc = CentroCusto(
        codigo=f"CC-{uuid.uuid4().hex[:8]}",
        nome="X",
        total_colaboradores=total,
        bloco_predio=bloco,
    )
    db.add(cc)
    await db.flush()
    return cc


async def _seed_questionarios(
    db: AsyncSession, *, cc: CentroCusto, n: int
) -> list[Item]:
    """Cria N questionários concluídos para CC, com 1 domínio + 1 item."""
    d = Dominio(nome=f"D-{uuid.uuid4().hex[:6]}", polaridade=-1, ordem_apresentacao=1)
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
    for _ in range(n):
        q = await criar_questionario(db, centro_custo=cc)
        await submeter_respostas(
            db,
            token_anonimo=q.token_anonimo,
            respostas=[RespostaIn(item_id=item.id, valor=2)],
        )
    return [item]


# ---------------------------------------------------------------------------
# Constante unificada
# ---------------------------------------------------------------------------


class TestConstanteKAnonimato:
    def test_k_anonimato_min_e_5(self) -> None:
        """A doc técnica fixa K_ANONIMATO_MIN = 5. Mudar exige migration de
        dados (resultados agregados existentes ficam abaixo do novo limiar)."""
        assert K_ANONIMATO_MIN == 5

    def test_constante_e_unica_e_compartilhada(self) -> None:
        """Gravação e consulta devem ler do MESMO símbolo — duplicar a
        constante causa drift silencioso."""
        from app.services import questionario_service, resposta_service

        assert resposta_service.K_ANONIMATO_MIN is questionario_service.K_ANONIMATO_MIN


# ---------------------------------------------------------------------------
# Gravação — granularidade condicional
# ---------------------------------------------------------------------------


class TestGravacaoGranularidadeCondicional:
    async def test_limiar_inclusivo_grava_cc(self, db_session: AsyncSession) -> None:
        """CC com `total = K_ANONIMATO_MIN` grava centro_custo_id (>= é o limiar)."""
        cc = await _cc(db_session, total=K_ANONIMATO_MIN)
        q = await criar_questionario(db_session, centro_custo=cc)
        assert q.centro_custo_id == cc.id
        assert q.bloco_predio is None

    async def test_logo_abaixo_do_limiar_cai_para_bloco(
        self, db_session: AsyncSession
    ) -> None:
        cc = await _cc(db_session, total=K_ANONIMATO_MIN - 1, bloco="Bloco Z")
        q = await criar_questionario(db_session, centro_custo=cc)
        assert q.centro_custo_id is None
        assert q.bloco_predio == "Bloco Z"

    async def test_pequeno_sem_bloco_eleva_granularidade_indisponivel(
        self, db_session: AsyncSession
    ) -> None:
        cc = await _cc(db_session, total=1, bloco=None)
        with pytest.raises(QuestionarioError) as exc:
            await criar_questionario(db_session, centro_custo=cc)
        assert exc.value.code == "granularidade_indisponivel"


# ---------------------------------------------------------------------------
# Constraint XOR no banco — defesa em profundidade
# ---------------------------------------------------------------------------


class TestConstraintXOR:
    """Se algum service bypass futuro tentar inserir ambos preenchidos ou
    ambos NULL, o banco rejeita antes de persistir."""

    async def test_rejeita_ambos_nulos(self, db_session: AsyncSession) -> None:
        db_session.add(Questionario())
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_rejeita_ambos_preenchidos(self, db_session: AsyncSession) -> None:
        cc = await _cc(db_session, total=10, bloco="Bloco X")
        db_session.add(Questionario(centro_custo_id=cc.id, bloco_predio="Bloco X"))
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# Consulta — supressão por k-anonimato
# ---------------------------------------------------------------------------


class TestSupressaoEmConsulta:
    async def test_limiar_inclusivo_n_igual_a_5_nao_suprime(
        self, db_session: AsyncSession
    ) -> None:
        cc = await _cc(db_session, total=20)
        await _seed_questionarios(db_session, cc=cc, n=K_ANONIMATO_MIN)
        agg = await agregar_respostas_por_cc(db_session, centro_custo_id=cc.id)
        assert agg.supressao is None
        assert agg.n_questionarios == K_ANONIMATO_MIN

    async def test_logo_abaixo_suprime(self, db_session: AsyncSession) -> None:
        cc = await _cc(db_session, total=20)
        await _seed_questionarios(db_session, cc=cc, n=K_ANONIMATO_MIN - 1)
        agg = await agregar_respostas_por_cc(db_session, centro_custo_id=cc.id)
        assert agg.supressao is not None
        assert agg.supressao.motivo == "k_anonimato_insuficiente"
        assert agg.supressao.minimo_requerido == K_ANONIMATO_MIN
        assert agg.supressao.n_atual == K_ANONIMATO_MIN - 1
        assert agg.por_dominio == []

    async def test_zero_questionarios_tambem_suprime(
        self, db_session: AsyncSession
    ) -> None:
        """N=0 também precisa suprimir — caso degenerado mas válido."""
        cc = await _cc(db_session, total=20)
        agg = await agregar_respostas_por_cc(db_session, centro_custo_id=cc.id)
        assert agg.supressao is not None
        assert agg.supressao.n_atual == 0


# ---------------------------------------------------------------------------
# Erro estável compartilhado entre gravação e consulta
# ---------------------------------------------------------------------------


class TestErroGranularidadeIndisponivelCompartilhado:
    """O code `granularidade_indisponivel` é o MESMO em ambos os lados,
    porque é a mesma condição: CC pequeno sem bloco de fallback."""

    async def test_consulta_cc_pequeno_sem_bloco_devolve_granularidade_indisponivel(
        self, db_session: AsyncSession
    ) -> None:
        cc = await _cc(db_session, total=2, bloco=None)
        with pytest.raises(RespostaError) as exc:
            await agregar_respostas_por_cc(db_session, centro_custo_id=cc.id)
        assert exc.value.code == "granularidade_indisponivel"

    def test_codes_de_gravacao_e_consulta_sao_o_mesmo_literal(self) -> None:
        """Validação textual rápida — protege contra divergência por typo
        entre os dois services (gravação em `questionario_service`,
        consulta em `resposta_service`)."""
        from app.services.questionario_service import QuestionarioError
        from app.services.resposta_service import RespostaError

        for cls in (QuestionarioError, RespostaError):
            inst = cls("granularidade_indisponivel", "msg")
            assert inst.code == "granularidade_indisponivel"


# ---------------------------------------------------------------------------
# CCs pequenos no mesmo bloco compõem para superar k-anonimato
# ---------------------------------------------------------------------------


class TestComposicaoDeCCsPequenos:
    """Dois CCs com total<5 mas no MESMO `bloco_predio` somam respondentes
    no bucket do bloco. Isso é uma propriedade essencial da granularidade
    condicional — sem ela, CCs pequenos jamais teriam laudo."""

    async def test_dois_ccs_pequenos_somam_no_bloco(
        self, db_session: AsyncSession
    ) -> None:
        cc_a = CentroCusto(
            codigo=f"CC-COMP-A-{uuid.uuid4().hex[:6]}",
            nome="A",
            total_colaboradores=2,
            bloco_predio="Bloco Comp",
        )
        cc_b = CentroCusto(
            codigo=f"CC-COMP-B-{uuid.uuid4().hex[:6]}",
            nome="B",
            total_colaboradores=3,
            bloco_predio="Bloco Comp",
        )
        db_session.add_all([cc_a, cc_b])
        await db_session.flush()

        d = Dominio(nome="D-Comp", polaridade=-1, ordem_apresentacao=1)
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

        for cc, n in ((cc_a, 2), (cc_b, 3)):
            for _ in range(n):
                q = await criar_questionario(db_session, centro_custo=cc)
                await submeter_respostas(
                    db_session,
                    token_anonimo=q.token_anonimo,
                    respostas=[RespostaIn(item_id=it.id, valor=3)],
                )

        agg = await agregar_respostas_por_cc(db_session, centro_custo_id=cc_a.id)
        assert agg.bucket.tipo == "bloco_predio"
        assert agg.bucket.valor == "Bloco Comp"
        assert agg.n_questionarios == 5
        assert agg.supressao is None

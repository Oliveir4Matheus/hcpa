"""Spec compliance — invariantes do schema (§7.1 e §7.2 da doc técnica).

Checks de DDL: check constraints, unique, índices e tipos. Esses invariantes
são defesa em profundidade — mesmo que algum service contorne a validação na
camada de aplicação, o banco rejeita.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_sha256
from app.models._base import (
    LembreteStatus,
    LembreteTipo,
    QuestionarioStatus,
    SessaoAdminEstado,
    StatusDistribuicao,
)
from app.models.core import CentroCusto, Dominio, Item, Questionario, Resposta
from app.models.operacional import (
    Credencial,
    Operador,
    SessaoAdmin,
)


# ---------------------------------------------------------------------------
# Check constraints declarados no modelo
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    """Check constraints garantem valores válidos mesmo em INSERT bruto."""

    def test_resposta_valor_constraint_existe(self) -> None:
        cks = {
            c.name for c in Resposta.__table__.constraints if c.name and "ck_" in c.name
        }
        assert "ck_respostas_valor" in cks

    def test_item_escala_tipo_constraint_existe(self) -> None:
        cks = {c.name for c in Item.__table__.constraints if c.name and "ck_" in c.name}
        assert "ck_itens_escala_tipo" in cks

    def test_dominio_polaridade_constraint_existe(self) -> None:
        cks = {
            c.name for c in Dominio.__table__.constraints if c.name and "ck_" in c.name
        }
        assert "ck_dominios_polaridade" in cks

    def test_questionario_xor_granularidade_constraint_existe(self) -> None:
        cks = {
            c.name
            for c in Questionario.__table__.constraints
            if c.name and "ck_" in c.name
        }
        assert "ck_questionarios_granularidade_xor" in cks


# ---------------------------------------------------------------------------
# Check constraints exercitados no banco
# ---------------------------------------------------------------------------


class TestCheckConstraintsNoBanco:
    async def test_resposta_valor_fora_intervalo_rejeitado(
        self, db_session: AsyncSession
    ) -> None:
        # cria dependências
        d = Dominio(nome="X", polaridade=-1, ordem_apresentacao=1)
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
        cc = CentroCusto(
            codigo=f"CC-{uuid.uuid4().hex[:8]}", nome="X", total_colaboradores=10
        )
        db_session.add(cc)
        await db_session.flush()
        q = Questionario(centro_custo_id=cc.id)
        db_session.add(q)
        await db_session.flush()

        # valor = 99 viola check 0..4
        db_session.add(
            Resposta(
                questionario_id=q.id,
                item_id=it.id,
                valor=99,
                submetida_em=datetime.now(timezone.utc).replace(
                    minute=0, second=0, microsecond=0
                ),
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_item_escala_tipo_invalida_rejeitada(
        self, db_session: AsyncSession
    ) -> None:
        d = Dominio(nome=f"D-{uuid.uuid4().hex[:6]}", polaridade=-1, ordem_apresentacao=1)
        db_session.add(d)
        await db_session.flush()
        db_session.add(
            Item(
                dominio_id=d.id,
                texto_pergunta="?",
                ordem_apresentacao=1,
                escala_tipo="Z",  # não é nem 'A' nem 'B'
                invertido=False,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_dominio_polaridade_invalida_rejeitada(
        self, db_session: AsyncSession
    ) -> None:
        db_session.add(
            Dominio(nome="P", polaridade=7, ordem_apresentacao=1)  # só -1 ou 1
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# Uniques que sustentam invariantes de negócio
# ---------------------------------------------------------------------------


class TestUniques:
    """Cada constraint UNIQUE protege um invariante específico — quebrar
    qualquer uma destas tem impacto direto no fluxo do produto."""

    def test_centros_custo_codigo_unique(self) -> None:
        col = CentroCusto.__table__.c["codigo"]
        assert col.unique is True

    def test_questionarios_token_anonimo_unique(self) -> None:
        col = Questionario.__table__.c["token_anonimo"]
        assert col.unique is True

    def test_credencial_senha_hmac_unique(self) -> None:
        """Senha gerada precisa ser única (lookup determinístico do login
        do respondente). Colisão é improvável, mas o constraint é proteção
        em profundidade."""
        # senha_hmac pode ser unique via column.unique OU via UniqueConstraint
        # nomeado — verificamos ambos os caminhos.
        col = Credencial.__table__.c["senha_hmac"]
        if not col.unique:
            named_uniques = {
                c.name
                for c in Credencial.__table__.constraints
                if getattr(c, "columns", None)
                and "senha_hmac" in {x.name for x in c.columns}
            }
            assert any("senha_hmac" in name for name in named_uniques if name)

    def test_credencial_senha_hash_e_pk(self) -> None:
        col = Credencial.__table__.c["senha_hash"]
        assert col.primary_key is True

    def test_credencial_token_sessao_temporario_unique(self) -> None:
        col = Credencial.__table__.c["token_sessao_temporario"]
        assert col.unique is True

    def test_operadores_email_unique(self) -> None:
        col = Operador.__table__.c["email"]
        assert col.unique is True

    def test_sessao_admin_token_hash_unique(self) -> None:
        """Token de sessão precisa ser único globalmente — duplicate
        permitiria sequestro silencioso."""
        col = SessaoAdmin.__table__.c["token_hash"]
        if not col.unique:
            named = {
                c.name
                for c in SessaoAdmin.__table__.constraints
                if getattr(c, "columns", None)
                and "token_hash" in {x.name for x in c.columns}
            }
            assert any("token_hash" in name for name in named if name)


# ---------------------------------------------------------------------------
# CITEXT no email do operador (case-insensitive)
# ---------------------------------------------------------------------------


class TestEmailOperadorCaseInsensitive:
    """`operadores.email` é CITEXT — login deve aceitar variações de caixa."""

    def test_tipo_email_e_citext(self) -> None:
        col = Operador.__table__.c["email"]
        # SQLAlchemy normaliza o nome do tipo
        assert col.type.__class__.__name__.upper() == "CITEXT"


# ---------------------------------------------------------------------------
# Enums esperados
# ---------------------------------------------------------------------------


class TestEnumsCanonicos:
    def test_questionario_status_canonico(self) -> None:
        assert {e.value for e in QuestionarioStatus} == {
            "iniciado",
            "concluido",
            "abandonado",
        }

    def test_status_distribuicao_canonico(self) -> None:
        assert {e.value for e in StatusDistribuicao} == {
            "pendente",
            "distribuida",
            "confirmada",
        }

    def test_lembrete_tipo_canonico(self) -> None:
        assert {e.value for e in LembreteTipo} == {"email", "sms"}

    def test_lembrete_status_canonico(self) -> None:
        assert {e.value for e in LembreteStatus} == {
            "pendente",
            "enviado",
            "falhou",
        }

    def test_sessao_admin_estado_canonico(self) -> None:
        assert {e.value for e in SessaoAdminEstado} == {
            "pendente_totp",
            "ativa",
            "revogada",
        }


# ---------------------------------------------------------------------------
# PII cifrada em repouso — colunas *_enc são bytea (LargeBinary)
# ---------------------------------------------------------------------------


class TestPIIArmazenadaCifrada:
    """Defesa em profundidade contra leak via pg_stat_statements / log:
    nenhum *_enc pode ser TEXT/VARCHAR (que apareceria como plaintext)."""

    def _check_largebinary(self, table_class, colname: str) -> None:
        col = table_class.__table__.c[colname]
        type_name = col.type.__class__.__name__
        assert type_name in {"LargeBinary", "BYTEA"}, (
            f"{table_class.__name__}.{colname} deveria ser LargeBinary, "
            f"é {type_name}"
        )

    def test_colaborador_import_nome_e_email_sao_bytea(self) -> None:
        from app.models.operacional import ColaboradorImport

        self._check_largebinary(ColaboradorImport, "nome_enc")
        self._check_largebinary(ColaboradorImport, "email_enc")

    def test_operador_pii_sao_bytea(self) -> None:
        self._check_largebinary(Operador, "nome_enc")
        self._check_largebinary(Operador, "sobrenome_enc")
        self._check_largebinary(Operador, "totp_secret_enc")


# ---------------------------------------------------------------------------
# HMAC indexável para lookup do respondente
# ---------------------------------------------------------------------------


class TestLookupRespondenteIndexado:
    """`credencial.senha_hmac` precisa permitir busca O(1) — argon2id sozinho
    forçaria iteração linear."""

    async def test_lookup_por_hmac_funciona(self, db_session: AsyncSession) -> None:
        cc = CentroCusto(
            codigo=f"CC-LK-{uuid.uuid4().hex[:6]}", nome="X", total_colaboradores=10
        )
        db_session.add(cc)
        await db_session.flush()
        senha = "senha-de-teste-LK-123"
        cred = Credencial(
            senha_hash="$argon2id$v=19$m=65536,t=3,p=4$fake$fake",
            senha_hmac=hmac_sha256(senha),
            centro_custo_id=cc.id,
        )
        db_session.add(cred)
        await db_session.flush()

        # busca direta — equivalente ao que o login faz.
        found = (
            await db_session.execute(
                select(Credencial).where(Credencial.senha_hmac == hmac_sha256(senha))
            )
        ).scalar_one()
        assert found.senha_hash == cred.senha_hash

    async def test_credencial_aceita_senha_hash_nullable_apenas_quando_distribuida(
        self,
    ) -> None:
        """Apenas para confirmar que `senha_hash` de Credencial é NOT NULL —
        diferente de `ColaboradorImport.senha_hash` que é nullable até distribuir."""
        col = Credencial.__table__.c["senha_hash"]
        assert col.nullable is False

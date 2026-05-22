"""Spec compliance — Auditabilidade total (cláusula 22 do contrato HCPA).

> toda ação admin gera log imutável (`auditoria`).

Invariantes:
- Toda ação admin sensível registra uma linha em `auditoria`.
- A trilha NUNCA armazena segredos (senhas em texto claro, tokens de
  sessão, secrets TOTP).
- `usuario` é o email do operador (ou "anonimo" para a submissão pública).
- `timestamp` é gerado pelo banco (`server_default=now()`), não pelo cliente.
- `meta` contém contadores e ids — nunca o conteúdo sensível.
"""

from __future__ import annotations

import uuid

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TOTP_DIGITS, TOTP_INTERVALO_SEGUNDOS
from app.models.core import CentroCusto
from app.models.operacional import Auditoria
from app.services import auth_service

COOKIE = "hcpa_admin_sessao"
SENHA = "senha-forte-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA})
    return {COOKIE: r.cookies[COOKIE]}


# ---------------------------------------------------------------------------
# Coluna `timestamp` é controlada pelo servidor
# ---------------------------------------------------------------------------


class TestEsquemaAuditoria:
    def test_timestamp_tem_default_now_no_servidor(self) -> None:
        col = Auditoria.__table__.c["timestamp"]
        assert col.server_default is not None
        assert "now()" in str(col.server_default.arg)

    def test_timestamp_e_indexado(self) -> None:
        """Trilha de auditoria precisa ser consultável por janela temporal."""
        col = Auditoria.__table__.c["timestamp"]
        assert col.index is True

    def test_auditoria_tem_uuid_pk(self) -> None:
        col = Auditoria.__table__.c["id"]
        assert col.primary_key is True
        assert col.server_default is not None and "gen_random_uuid" in str(
            col.server_default.arg
        )


# ---------------------------------------------------------------------------
# Eventos do ciclo de auth
# ---------------------------------------------------------------------------


class TestAuditoriaAuth:
    async def test_login_sucesso_registra_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-login-ok-{uuid.uuid4().hex[:6]}@example.com"
        await _login(client, db_session, email=email)
        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email, Auditoria.acao == "login_sucesso"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1
        assert entries[-1].recurso == "sessao_admin"

    async def test_login_falhou_registra_motivo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-login-bad-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=email, senha=SENHA)
        await client.post("/v1/auth/login", json={"email": email, "senha": "errada"})
        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email, Auditoria.acao == "login_falhou"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1
        assert entries[-1].meta is not None
        assert "motivo" in entries[-1].meta

    async def test_login_email_inexistente_registra_com_motivo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Mesmo `login_falhou`, mas com motivo distinto — útil para análise
        forense, sem expor a distinção ao cliente HTTP."""
        email_ghost = f"ghost-{uuid.uuid4().hex[:6]}@example.com"
        await client.post(
            "/v1/auth/login", json={"email": email_ghost, "senha": "x"}
        )
        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email_ghost, Auditoria.acao == "login_falhou"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1
        assert entries[-1].meta["motivo"] == "operador_inexistente"

    async def test_logout_registra_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-logout-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        await client.post("/v1/auth/logout", cookies=cookies)
        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email, Auditoria.acao == "logout"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1

    async def test_totp_setup_e_confirm_auditados(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-totp-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        setup = await client.post("/v1/auth/totp/setup", cookies=cookies)
        secret = setup.json()["secret"]
        totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVALO_SEGUNDOS)
        await client.post(
            "/v1/auth/totp/confirm", json={"codigo": totp.now()}, cookies=cookies
        )
        acoes = (
            (
                await db_session.execute(
                    select(Auditoria.acao).where(
                        Auditoria.usuario == email,
                        Auditoria.acao.in_(["totp_setup", "totp_confirm_ok"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "totp_setup" in acoes
        assert "totp_confirm_ok" in acoes


# ---------------------------------------------------------------------------
# Eventos do pipeline de colaboradores
# ---------------------------------------------------------------------------


class TestAuditoriaPipelineColaboradores:
    async def _seed_cc(self, db: AsyncSession) -> str:
        codigo = f"CC-AUD-{uuid.uuid4().hex[:6]}"
        cc = CentroCusto(codigo=codigo, nome=codigo, total_colaboradores=10)
        db.add(cc)
        await db.flush()
        return codigo

    async def test_centros_custo_commit_auditado(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-cc-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        await client.post(
            "/v1/centros-custo/import/commit",
            json={"itens": [{"codigo": f"CC-A-{uuid.uuid4().hex[:6]}", "nome": "X"}]},
            cookies=cookies,
        )
        rows = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email,
                        Auditoria.acao == "centros_custo_import_commit",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1
        assert "criados" in rows[-1].meta

    async def test_colaboradores_commit_auditado(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-col-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        codigo = await self._seed_cc(db_session)
        await client.post(
            "/v1/colaboradores/import/commit",
            json={
                "itens": [
                    {
                        "matricula": f"M-{uuid.uuid4().hex[:6]}",
                        "nome": "X",
                        "email": "x@example.com",
                        "centro_custo_codigo": codigo,
                    }
                ]
            },
            cookies=cookies,
        )
        rows = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email,
                        Auditoria.acao == "colaboradores_import_commit",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1

    async def test_credenciais_distribuidas_auditado_sem_senhas_no_metadata(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A senha em texto claro aparece SÓ no body HTTP do /distribuir.
        Auditoria registra apenas contadores."""
        email = f"audit-dist-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        codigo = await self._seed_cc(db_session)
        await client.post(
            "/v1/colaboradores/import/commit",
            json={
                "itens": [
                    {
                        "matricula": f"D-{uuid.uuid4().hex[:6]}",
                        "nome": "X",
                        "email": "x@example.com",
                        "centro_custo_codigo": codigo,
                    }
                ]
            },
            cookies=cookies,
        )
        r = await client.post("/v1/colaboradores/distribuir", cookies=cookies)
        senhas = [c["senha"] for c in r.json()["credenciais"]]

        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email,
                        Auditoria.acao == "credenciais_distribuidas",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) >= 1
        meta_str = str(entries[-1].meta)
        for senha_clara in senhas:
            assert senha_clara not in meta_str, (
                "Auditoria de distribuição NUNCA pode conter senha em texto claro."
            )

    async def test_descarte_auditado(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-desc-{uuid.uuid4().hex[:6]}@example.com"
        cookies = await _login(client, db_session, email=email)
        codigo = await self._seed_cc(db_session)
        await client.post(
            "/v1/colaboradores/import/commit",
            json={
                "itens": [
                    {
                        "matricula": f"X-{uuid.uuid4().hex[:6]}",
                        "nome": "X",
                        "email": "x@example.com",
                        "centro_custo_codigo": codigo,
                    }
                ]
            },
            cookies=cookies,
        )
        await client.post("/v1/colaboradores/distribuir", cookies=cookies)
        await client.post(
            "/v1/colaboradores/descartar", json={"confirmar": True}, cookies=cookies
        )
        rows = (
            (
                await db_session.execute(
                    select(Auditoria).where(
                        Auditoria.usuario == email,
                        Auditoria.acao == "colaborador_import_descartado",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1
        assert rows[-1].meta["descartados"] >= 1


# ---------------------------------------------------------------------------
# Trilha não vaza segredos
# ---------------------------------------------------------------------------


class TestAuditoriaNaoVazaSegredos:
    """Varredura defensiva: nenhuma linha de auditoria pode conter strings
    sensíveis nos campos `usuario`, `recurso`, ou no JSONB `meta`."""

    async def test_meta_de_login_falhou_nao_contem_senha(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"audit-leak-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=email, senha=SENHA)
        senha_secreta = "senha-secreta-que-nao-pode-vazar-XYZ"
        await client.post(
            "/v1/auth/login", json={"email": email, "senha": senha_secreta}
        )
        entries = (
            (
                await db_session.execute(
                    select(Auditoria).where(Auditoria.usuario == email)
                )
            )
            .scalars()
            .all()
        )
        for e in entries:
            assert senha_secreta not in str(e.meta or {})
            assert senha_secreta not in (e.recurso or "")

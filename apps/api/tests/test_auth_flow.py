"""Integration tests do fluxo de autenticação do operador.

Bate na API real via httpx + ASGITransport (conftest), com `db_session` em
savepoint para isolamento. Cobre login sem/com TOTP, sessões, logout,
e códigos de erro estáveis.
"""

from __future__ import annotations

import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TOTP_DIGITS, TOTP_INTERVALO_SEGUNDOS
from app.services import auth_service

COOKIE = "hcpa_admin_sessao"


async def _criar(db: AsyncSession, email: str, senha: str = "senha-forte-1234") -> object:
    return await auth_service.criar_operador(db, email=email, senha=senha, nome="Ana")


async def test_login_sem_totp_seta_cookie_e_libera_me(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _criar(db_session, "ana@example.com")

    r = await client.post(
        "/v1/auth/login",
        json={"email": "ana@example.com", "senha": "senha-forte-1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["totp_required"] is False
    assert body["operador"]["email"] == "ana@example.com"
    assert COOKIE in r.cookies

    me = await client.get("/v1/auth/me", cookies={COOKIE: r.cookies[COOKIE]})
    assert me.status_code == 200
    assert me.json()["email"] == "ana@example.com"


async def test_logout_invalida_a_sessao(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _criar(db_session, "logout@example.com")
    r = await client.post(
        "/v1/auth/login",
        json={"email": "logout@example.com", "senha": "senha-forte-1234"},
    )
    token = r.cookies[COOKIE]

    out = await client.post("/v1/auth/logout", cookies={COOKIE: token})
    assert out.status_code == 200

    me = await client.get("/v1/auth/me", cookies={COOKIE: token})
    assert me.status_code == 401


async def test_senha_errada_devolve_codigo_estavel(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _criar(db_session, "erro@example.com")
    r = await client.post(
        "/v1/auth/login",
        json={"email": "erro@example.com", "senha": "errada"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "credenciais_invalidas"


async def test_operador_inexistente_usa_o_mesmo_codigo(client: AsyncClient) -> None:
    """Mesmo `code` que senha errada — evita enumeração de operadores válidos."""
    r = await client.post(
        "/v1/auth/login",
        json={"email": "nao-existe@example.com", "senha": "qualquer"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "credenciais_invalidas"


async def test_me_sem_cookie_retorna_sessao_ausente(client: AsyncClient) -> None:
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_ausente"


async def test_fluxo_completo_com_totp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Login → setup → confirm → próximo login exige TOTP → verify → /me ok."""
    await _criar(db_session, "totp@example.com")

    # 1. Login inicial (sem TOTP ainda)
    r = await client.post(
        "/v1/auth/login",
        json={"email": "totp@example.com", "senha": "senha-forte-1234"},
    )
    assert r.status_code == 200
    sess_inicial = r.cookies[COOKIE]

    # 2. Setup TOTP → recebe secret
    setup = await client.post("/v1/auth/totp/setup", cookies={COOKIE: sess_inicial})
    assert setup.status_code == 200
    secret = setup.json()["secret"]

    # 3. Confirm com código do app autenticador
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVALO_SEGUNDOS)
    confirm = await client.post(
        "/v1/auth/totp/confirm",
        json={"codigo": totp.now()},
        cookies={COOKIE: sess_inicial},
    )
    assert confirm.status_code == 200

    # 4. Logout antes do próximo login
    await client.post("/v1/auth/logout", cookies={COOKIE: sess_inicial})

    # 5. Novo login agora indica pendência de TOTP
    r2 = await client.post(
        "/v1/auth/login",
        json={"email": "totp@example.com", "senha": "senha-forte-1234"},
    )
    assert r2.status_code == 200
    assert r2.json()["totp_required"] is True
    sess_pendente = r2.cookies[COOKIE]

    # 6. /me ainda não — sessão está pendente_totp, não ativa
    me_pendente = await client.get("/v1/auth/me", cookies={COOKIE: sess_pendente})
    assert me_pendente.status_code == 401

    # 7. Verifica TOTP → sessão vira ativa
    verify = await client.post(
        "/v1/auth/totp/verify",
        json={"codigo": totp.now()},
        cookies={COOKIE: sess_pendente},
    )
    assert verify.status_code == 200
    sess_ativa = verify.cookies.get(COOKIE, sess_pendente)

    me = await client.get("/v1/auth/me", cookies={COOKIE: sess_ativa})
    assert me.status_code == 200
    assert me.json()["totp_enabled"] is True


async def test_totp_codigo_invalido_durante_verify(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _criar(db_session, "totp-bad@example.com")
    r = await client.post(
        "/v1/auth/login",
        json={"email": "totp-bad@example.com", "senha": "senha-forte-1234"},
    )
    sess = r.cookies[COOKIE]

    setup = await client.post("/v1/auth/totp/setup", cookies={COOKIE: sess})
    secret = setup.json()["secret"]
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVALO_SEGUNDOS)
    await client.post(
        "/v1/auth/totp/confirm",
        json={"codigo": totp.now()},
        cookies={COOKIE: sess},
    )
    await client.post("/v1/auth/logout", cookies={COOKIE: sess})

    r2 = await client.post(
        "/v1/auth/login",
        json={"email": "totp-bad@example.com", "senha": "senha-forte-1234"},
    )
    sess_pendente = r2.cookies[COOKIE]

    ruim = await client.post(
        "/v1/auth/totp/verify",
        json={"codigo": "000000"},
        cookies={COOKIE: sess_pendente},
    )
    assert ruim.status_code == 401
    assert ruim.json()["detail"]["code"] == "totp_invalido"


async def test_email_duplicado_no_criar_operador(db_session: AsyncSession) -> None:
    await _criar(db_session, "dup@example.com")
    try:
        await _criar(db_session, "dup@example.com")
    except auth_service.AuthError as exc:
        assert exc.code == "email_em_uso"
    else:
        raise AssertionError("esperava AuthError email_em_uso")

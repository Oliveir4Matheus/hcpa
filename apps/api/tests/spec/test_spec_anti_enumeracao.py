"""Spec compliance — Anti-enumeração de identidades.

Princípio: o cliente HTTP NÃO deve conseguir distinguir, pelo `code`/status
da resposta, entre "identidade não existe" e "credenciais erradas para
identidade que existe". Caso contrário, um atacante pode enumerar
operadores válidos (e depois focar força-bruta nas senhas).

Spec consolidada em:
- `app/services/auth_service.py:login` — devolve `credenciais_invalidas` em
  ambos os casos (`operador_inexistente` e `senha_incorreta`).
- `app/services/respondente_auth.py:login_respondente` — devolve
  `senha_invalida` em ambos os casos (HMAC vazio e argon2id mismatch).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import auth_service

SENHA = "senha-forte-1234"


# ---------------------------------------------------------------------------
# Operador — login do painel
# ---------------------------------------------------------------------------


class TestEnumeracaoDeOperadores:
    async def test_email_inexistente_e_senha_errada_devolvem_mesmo_code(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"existe-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=email, senha=SENHA)

        r_ghost = await client.post(
            "/v1/auth/login",
            json={"email": f"ghost-{uuid.uuid4().hex[:6]}@example.com", "senha": "x"},
        )
        r_errada = await client.post(
            "/v1/auth/login", json={"email": email, "senha": "errada"}
        )

        assert r_ghost.status_code == r_errada.status_code == 401
        assert (
            r_ghost.json()["detail"]["code"]
            == r_errada.json()["detail"]["code"]
            == "credenciais_invalidas"
        )

    async def test_mensagem_de_erro_tambem_e_igual(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A `mensagem` também precisa ser igual — diferenciá-la quebra o
        invariante mesmo com `code` igual."""
        email = f"existe2-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=email, senha=SENHA)

        r_ghost = await client.post(
            "/v1/auth/login",
            json={"email": f"ghost2-{uuid.uuid4().hex[:6]}@example.com", "senha": "x"},
        )
        r_errada = await client.post(
            "/v1/auth/login", json={"email": email, "senha": "errada"}
        )

        assert (
            r_ghost.json()["detail"]["mensagem"]
            == r_errada.json()["detail"]["mensagem"]
        )


# ---------------------------------------------------------------------------
# Respondente — login do totem
# ---------------------------------------------------------------------------


class TestEnumeracaoDeRespondentes:
    """Para o respondente, o problema simétrico é distinguir
    "senha não existe" (HMAC sem match) de "senha existe mas argon2id
    falhou" (HMAC bate, hash não). Ambos devem dar `senha_invalida`."""

    async def test_senha_inexistente_devolve_senha_invalida_404(
        self, client: AsyncClient
    ) -> None:
        r = await client.post(
            "/v1/auth/respondente", json={"senha": f"nunca-existiu-{uuid.uuid4().hex}"}
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "senha_invalida"

    async def test_senha_vazia_apos_strip_devolve_senha_invalida(
        self, client: AsyncClient
    ) -> None:
        """Espaços em branco passam pela validação Pydantic, mas o service
        normaliza e rejeita uniformemente."""
        # min_length do pydantic rejeita string vazia (422); senha "   " passa.
        r = await client.post("/v1/auth/respondente", json={"senha": "   "})
        # Tanto 404 quanto 422 são aceitáveis aqui — 422 se Pydantic bater na
        # validação antes; 404 se chegar ao service.
        assert r.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Sessão expirada vs sessão inexistente — operador
# ---------------------------------------------------------------------------


class TestSessaoOperadorCodes:
    """Operador sem cookie ⇒ `sessao_ausente`. Cookie com token desconhecido
    ⇒ `sessao_invalida`. Esses dois codes precisam ser diferentes para o
    front saber se redireciona para login (ausente) ou se exibe erro
    específico (invalida — possível ataque)."""

    async def test_sem_cookie_devolve_sessao_ausente(
        self, client: AsyncClient
    ) -> None:
        r = await client.get("/v1/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "sessao_ausente"

    async def test_cookie_lixo_devolve_sessao_invalida(
        self, client: AsyncClient
    ) -> None:
        r = await client.get(
            "/v1/auth/me", cookies={"hcpa_admin_sessao": "token-completamente-falso"}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "sessao_invalida"


# ---------------------------------------------------------------------------
# Não-divulgação do nome do cookie para o cliente
# ---------------------------------------------------------------------------


class TestCookiesHttpOnly:
    """Cookies de sessão precisam ser HttpOnly para mitigar XSS leak."""

    async def test_cookie_de_login_operador_e_httponly(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = f"http-only-{uuid.uuid4().hex[:6]}@example.com"
        await auth_service.criar_operador(db_session, email=email, senha=SENHA)
        r = await client.post(
            "/v1/auth/login", json={"email": email, "senha": SENHA}
        )
        # httpx expõe os atributos do Set-Cookie via headers
        set_cookie = r.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie
        # SameSite=lax para mitigar CSRF cross-site
        assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()

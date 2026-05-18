"""Unit tests de `app.core.security`.

Cobre senha (argon2id), token de sessão (urlsafe + sha256), e TOTP (pyotp).
Nenhum I/O, nenhuma fixture de DB.
"""

from __future__ import annotations

import base64

import pyotp
import pytest

from app.core.security import (
    TOKEN_SESSAO_BYTES,
    TOTP_DIGITS,
    TOTP_INTERVALO_SEGUNDOS,
    hash_senha,
    hash_token_sessao,
    novo_token_sessao,
    novo_totp_secret,
    precisa_rehash,
    totp_provisioning_uri,
    verifica_totp,
    verify_senha,
)


class TestSenha:
    def test_hash_diferente_a_cada_chamada(self) -> None:
        h1 = hash_senha("minha-senha")
        h2 = hash_senha("minha-senha")
        assert h1 != h2  # salt aleatório por hash
        assert h1.startswith("$argon2id$")

    def test_verify_aceita_senha_correta(self) -> None:
        h = hash_senha("xyz")
        assert verify_senha("xyz", h) is True

    def test_verify_rejeita_senha_errada(self) -> None:
        h = hash_senha("xyz")
        assert verify_senha("abc", h) is False

    def test_verify_rejeita_hash_lixo_sem_levantar(self) -> None:
        assert verify_senha("xyz", "nao-eh-um-hash-argon2") is False

    @pytest.mark.parametrize("entrada", ["", None, 123])
    def test_hash_recusa_entrada_invalida(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            hash_senha(entrada)  # type: ignore[arg-type]

    def test_precisa_rehash_false_para_hash_atual(self) -> None:
        h = hash_senha("xyz")
        assert precisa_rehash(h) is False


class TestTokenSessao:
    def test_token_unico_por_chamada(self) -> None:
        tokens = {novo_token_sessao() for _ in range(50)}
        assert len(tokens) == 50

    def test_token_decodifica_em_url_safe(self) -> None:
        t = novo_token_sessao()
        decoded = base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))
        assert len(decoded) == TOKEN_SESSAO_BYTES

    def test_hash_determinístico(self) -> None:
        t = "qualquer-coisa-fixa"
        assert hash_token_sessao(t) == hash_token_sessao(t)
        assert len(hash_token_sessao(t)) == 32  # sha-256


class TestTotp:
    def test_secret_base32_valido(self) -> None:
        s = novo_totp_secret()
        assert len(s) == 32  # 20 bytes → 32 chars base32
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s)

    def test_provisioning_uri_inclui_issuer_e_conta(self) -> None:
        uri = totp_provisioning_uri("ABCDEFGHIJKLMNOP", "ana@hcpa.example.com")
        assert uri.startswith("otpauth://totp/")
        assert "issuer=Plataforma+HCPA" in uri or "issuer=Plataforma%20HCPA" in uri
        assert "ana%40hcpa.example.com" in uri

    def test_verifica_codigo_atual(self) -> None:
        s = novo_totp_secret()
        codigo = pyotp.TOTP(s, digits=TOTP_DIGITS, interval=TOTP_INTERVALO_SEGUNDOS).now()
        assert verifica_totp(s, codigo) is True

    def test_rejeita_codigo_errado(self) -> None:
        s = novo_totp_secret()
        assert verifica_totp(s, "000000") is False

    @pytest.mark.parametrize("entrada", ["", "abc", "12345", "abc123"])
    def test_rejeita_entrada_nao_numerica(self, entrada: str) -> None:
        s = novo_totp_secret()
        assert verifica_totp(s, entrada) is False

"""Helpers de autenticação: senha (argon2id), sessão (token + sha256), TOTP.

- Argon2id para senha de operador: parâmetros padrão da `argon2-cffi` v23+
  (time=3, memory=64MB, parallelism=4) são recomendação OWASP 2024.
- Token de sessão: 32 bytes URL-safe. Persistimos apenas o SHA-256 do token
  no banco — compromisso do DB não vaza sessões ativas.
- TOTP: pyotp (RFC 6238). Janela de ±1 step (default 30s) para tolerar
  pequeno desvio de relógio do app autenticador.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher: Final = PasswordHasher()

TOKEN_SESSAO_BYTES: Final = 32
TOTP_DIGITS: Final = 6
TOTP_INTERVALO_SEGUNDOS: Final = 30
TOTP_JANELA_TOLERANCIA: Final = 1
TOTP_ISSUER: Final = "Plataforma HCPA"


def hash_senha(senha: str) -> str:
    """Gera hash argon2id."""
    if not isinstance(senha, str) or not senha:
        raise ValueError("senha vazia ou inválida")
    return _hasher.hash(senha)


def verify_senha(senha: str, hashed: str) -> bool:
    """Valida senha contra hash armazenado. Retorna False em qualquer falha."""
    try:
        _hasher.verify(hashed, senha)
        return True
    except (VerifyMismatchError, ValueError):
        return False


def precisa_rehash(hashed: str) -> bool:
    """True se o hash foi gerado com parâmetros diferentes dos atuais."""
    return _hasher.check_needs_rehash(hashed)


def novo_token_sessao() -> str:
    """Token opaco URL-safe (~43 chars base64url) com 256 bits de entropia."""
    return secrets.token_urlsafe(TOKEN_SESSAO_BYTES)


def hash_token_sessao(token: str) -> bytes:
    """SHA-256 do token, persistido no banco para lookup constant-time."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def novo_totp_secret() -> str:
    """Secret base32 de 20 bytes (160 bits), padrão pyotp/Google Authenticator."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, conta: str) -> str:
    """URI otpauth:// para o app autenticador (QR code é gerado no front)."""
    return pyotp.TOTP(
        secret,
        digits=TOTP_DIGITS,
        interval=TOTP_INTERVALO_SEGUNDOS,
    ).provisioning_uri(name=conta, issuer_name=TOTP_ISSUER)


def verifica_totp(secret: str, codigo: str) -> bool:
    """Valida código TOTP com janela de tolerância padrão (±1 step)."""
    if not codigo or not codigo.strip().isdigit():
        return False
    totp = pyotp.TOTP(
        secret,
        digits=TOTP_DIGITS,
        interval=TOTP_INTERVALO_SEGUNDOS,
    )
    return totp.verify(codigo.strip(), valid_window=TOTP_JANELA_TOLERANCIA)

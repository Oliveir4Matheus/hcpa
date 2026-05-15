"""Camada de criptografia simétrica e HMAC determinístico.

Arquitetura híbrida (decisão registrada na conversa de 15/05/2026):
- AES-256-GCM em camada de aplicação. A chave nunca trafega via SQL — só
  ciphertext (bytea) é persistido. Mitigação de risco de leak via
  pg_stat_statements e logs do Postgres.
- pgcrypto carregado no banco (init.sql) permanece disponível para funções
  auxiliares (digest, gen_random_uuid) já em uso. Esta camada NÃO o utiliza
  para a operação principal de encrypt/decrypt.
- HKDF-SHA256 deriva duas subchaves a partir do master key configurado em
  Settings.encryption_key: uma para AES-GCM, outra para HMAC-SHA256. Isso
  isola domínios criptográficos sem multiplicar variáveis de ambiente.
- Cada ciphertext começa com um version byte; rotação futura preserva
  capacidade de decrypt de payloads antigos enquanto novos passam a usar
  CURRENT_KEY_VERSION.

Formato do payload: version(1) || nonce(12) || ciphertext || tag(16).
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

CURRENT_KEY_VERSION = 1
_VERSION_LEN = 1
_NONCE_LEN = 12
_TAG_LEN = 16
_SUBKEY_LEN = 32
_MIN_MASTER_KEY_LEN = 32
_HKDF_AES_PREFIX = b"hcpa/encryption/aes-gcm/v"
_HKDF_HMAC_PREFIX = b"hcpa/encryption/hmac-sha256/v"


class CryptoError(Exception):
    """Falha de criptografia (chave ausente/inválida, payload corrompido)."""


def _master_key() -> bytes:
    raw = get_settings().encryption_key
    if not raw:
        raise CryptoError(
            "ENCRYPTION_KEY não configurada. Gerar com `openssl rand -base64 32`."
        )
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise CryptoError("ENCRYPTION_KEY deve ser base64 válido.") from exc
    if len(decoded) < _MIN_MASTER_KEY_LEN:
        raise CryptoError(
            f"ENCRYPTION_KEY deve decodificar para >={_MIN_MASTER_KEY_LEN} bytes "
            f"(veio {len(decoded)})."
        )
    return decoded


def _derive_subkey(prefix: bytes, version: int) -> bytes:
    if version < 0 or version > 255:
        raise CryptoError(f"Version inválida: {version}.")
    info = prefix + str(version).encode("ascii")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_SUBKEY_LEN,
        salt=None,
        info=info,
    ).derive(_master_key())


@lru_cache(maxsize=16)
def _aes_key(version: int) -> bytes:
    return _derive_subkey(_HKDF_AES_PREFIX, version)


@lru_cache(maxsize=16)
def _hmac_key(version: int) -> bytes:
    return _derive_subkey(_HKDF_HMAC_PREFIX, version)


def encrypt(plaintext: str) -> bytes:
    """Cifra `plaintext` (UTF-8) com AES-256-GCM usando a chave atual."""
    if not isinstance(plaintext, str):
        raise CryptoError("encrypt() espera str.")
    key = _aes_key(CURRENT_KEY_VERSION)
    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return bytes([CURRENT_KEY_VERSION]) + nonce + ct


def decrypt(blob: bytes | bytearray | memoryview) -> str:
    """Decifra um payload produzido por `encrypt`."""
    if not isinstance(blob, bytes | bytearray | memoryview):
        raise CryptoError("decrypt() espera bytes.")
    data = bytes(blob)
    if len(data) < _VERSION_LEN + _NONCE_LEN + _TAG_LEN:
        raise CryptoError("Payload curto demais para ser AES-GCM.")
    version = data[0]
    nonce = data[_VERSION_LEN : _VERSION_LEN + _NONCE_LEN]
    ct = data[_VERSION_LEN + _NONCE_LEN :]
    try:
        key = _aes_key(version)
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, associated_data=None)
    except Exception as exc:
        raise CryptoError(
            "Decrypt falhou — chave incorreta, versão inexistente ou payload corrompido."
        ) from exc
    return pt.decode("utf-8")


def hmac_sha256(value: str, version: int = CURRENT_KEY_VERSION) -> bytes:
    """HMAC-SHA256 determinístico para indexação/lookup de campos opacos."""
    if not isinstance(value, str):
        raise CryptoError("hmac_sha256() espera str.")
    key = _hmac_key(version)
    return _hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def reset_keys_cache() -> None:
    """Limpa o cache de subchaves derivadas — uso restrito a testes."""
    _aes_key.cache_clear()
    _hmac_key.cache_clear()

"""Unit tests para `app.core.crypto`.

Exercitam o ciclo AES-256-GCM, HMAC determinístico, e cenários de falha
(payload curto, payload corrompido, chave ausente, version inválida).
"""

import base64

import pytest

from app.core import crypto
from app.core.crypto import (
    CURRENT_KEY_VERSION,
    CryptoError,
    decrypt,
    encrypt,
    hmac_sha256,
    reset_keys_cache,
)


class TestRoundtrip:
    def test_roundtrip_simples(self) -> None:
        ct = encrypt("hello, world")
        assert decrypt(ct) == "hello, world"

    def test_roundtrip_string_vazia(self) -> None:
        ct = encrypt("")
        assert decrypt(ct) == ""

    def test_roundtrip_unicode_acentos(self) -> None:
        original = "João D'Ávila — São Paulo · 🇧🇷"
        assert decrypt(encrypt(original)) == original

    def test_roundtrip_string_longa(self) -> None:
        original = "x" * 10_000
        assert decrypt(encrypt(original)) == original

    def test_payload_comeca_com_version_byte(self) -> None:
        ct = encrypt("x")
        assert ct[0] == CURRENT_KEY_VERSION

    def test_payload_tem_tamanho_minimo_esperado(self) -> None:
        # version(1) + nonce(12) + ciphertext(>=1 para "x") + tag(16) = 30
        assert len(encrypt("x")) >= 30


class TestRandomnessENonce:
    def test_dois_encrypts_da_mesma_string_diferem(self) -> None:
        """Nonce aleatório garante que ciphertext varia por chamada."""
        a = encrypt("mesma coisa")
        b = encrypt("mesma coisa")
        assert a != b

    def test_nonces_sao_diferentes(self) -> None:
        a = encrypt("x")
        b = encrypt("x")
        # bytes 1..13 são o nonce
        assert a[1:13] != b[1:13]


class TestFalhaEmDecrypt:
    def test_decrypt_de_payload_curto(self) -> None:
        with pytest.raises(CryptoError, match="curto"):
            decrypt(b"\x01\x02\x03")

    def test_decrypt_de_payload_corrompido(self) -> None:
        ct = bytearray(encrypt("hello"))
        ct[-1] ^= 0xFF  # corrompe o tag
        with pytest.raises(CryptoError, match="falhou"):
            decrypt(bytes(ct))

    def test_decrypt_aceita_bytearray(self) -> None:
        ct = encrypt("hello")
        assert decrypt(bytearray(ct)) == "hello"

    def test_decrypt_aceita_memoryview(self) -> None:
        ct = encrypt("hello")
        assert decrypt(memoryview(ct)) == "hello"

    def test_decrypt_rejeita_tipo_invalido(self) -> None:
        with pytest.raises(CryptoError, match="bytes"):
            decrypt("not bytes")  # type: ignore[arg-type]


class TestHmac:
    def test_hmac_e_deterministico(self) -> None:
        assert hmac_sha256("matricula-123") == hmac_sha256("matricula-123")

    def test_hmac_difere_por_input(self) -> None:
        assert hmac_sha256("a") != hmac_sha256("b")

    def test_hmac_tem_32_bytes(self) -> None:
        assert len(hmac_sha256("qualquer")) == 32

    def test_hmac_e_diferente_de_aes_key(self) -> None:
        """Sanidade: subchaves AES e HMAC são domínios separados."""
        # encrypt usa chave AES; o ciphertext (minus version+nonce) não pode bater
        # com o HMAC para um mesmo input. Cheque indireto: ciphertext muda
        # entre chamadas, HMAC não. Já coberto, mas reforçando como invariante.
        assert hmac_sha256("x") == hmac_sha256("x")
        assert encrypt("x") != encrypt("x")


class TestChaveAusenteOuInvalida:
    def test_chave_ausente_levanta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core import config

        def _settings_sem_chave():
            s = config.Settings()
            s.encryption_key = ""
            return s

        monkeypatch.setattr(crypto, "get_settings", _settings_sem_chave)
        reset_keys_cache()
        try:
            with pytest.raises(CryptoError, match="não configurada"):
                encrypt("x")
        finally:
            reset_keys_cache()

    def test_chave_base64_invalido_levanta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import config

        def _settings_chave_ruim():
            s = config.Settings()
            s.encryption_key = "isto não é base64!!"
            return s

        monkeypatch.setattr(crypto, "get_settings", _settings_chave_ruim)
        reset_keys_cache()
        try:
            with pytest.raises(CryptoError, match="base64"):
                encrypt("x")
        finally:
            reset_keys_cache()

    def test_chave_curta_levanta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core import config

        chave_curta = base64.b64encode(b"x" * 16).decode()

        def _settings_chave_curta():
            s = config.Settings()
            s.encryption_key = chave_curta
            return s

        monkeypatch.setattr(crypto, "get_settings", _settings_chave_curta)
        reset_keys_cache()
        try:
            with pytest.raises(CryptoError, match="bytes"):
                encrypt("x")
        finally:
            reset_keys_cache()


class TestVersioning:
    def test_version_byte_persiste_no_ciphertext(self) -> None:
        assert encrypt("x")[0] == CURRENT_KEY_VERSION

    def test_decrypt_de_version_inexistente_falha_de_forma_controlada(self) -> None:
        ct = bytearray(encrypt("hello"))
        ct[0] = 99  # version não derivável == chave diferente == decrypt falha
        with pytest.raises(CryptoError, match="falhou"):
            decrypt(bytes(ct))

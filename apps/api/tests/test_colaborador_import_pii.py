"""Integration tests para campos PII criptografados em `colaborador_import`.

Valida que:
- ORM armazena ciphertext (não plaintext) nas colunas `*_enc`
- Acesso via property retorna plaintext
- Bytea persistido bate com o formato AES-GCM esperado
- None continua sendo None (campos opcionais)
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import CURRENT_KEY_VERSION
from app.models.core import CentroCusto
from app.models.operacional import ColaboradorImport


async def _make_centro_custo(db: AsyncSession) -> CentroCusto:
    cc = CentroCusto(codigo=f"CC-{uuid.uuid4().hex[:8]}", nome="Centro de Teste")
    db.add(cc)
    await db.flush()
    return cc


async def test_nome_e_email_persistidos_cifrados(db_session: AsyncSession) -> None:
    cc = await _make_centro_custo(db_session)
    col = ColaboradorImport(
        matricula="MAT-001",
        senha_hash="$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTU",
        centro_custo_id=cc.id,
    )
    col.nome = "João da Silva"
    col.email = "joao.silva@hcpa.edu.br"
    db_session.add(col)
    await db_session.flush()

    # Confere via SQL bruto que o banco tem bytea, não plaintext.
    raw = await db_session.execute(
        text(
            "SELECT nome_enc, email_enc FROM colaborador_import WHERE matricula = :m"
        ),
        {"m": "MAT-001"},
    )
    nome_bytes, email_bytes = raw.one()
    assert isinstance(nome_bytes, bytes | memoryview)
    nome_bytes = bytes(nome_bytes)
    email_bytes = bytes(email_bytes)
    assert b"Jo\xc3\xa3o" not in nome_bytes
    assert b"joao.silva" not in email_bytes
    # Formato esperado: version(1) + nonce(12) + ct + tag(16)
    assert nome_bytes[0] == CURRENT_KEY_VERSION
    assert len(nome_bytes) >= 30
    assert email_bytes[0] == CURRENT_KEY_VERSION


async def test_property_decripta_no_acesso(db_session: AsyncSession) -> None:
    cc = await _make_centro_custo(db_session)
    col = ColaboradorImport(
        matricula="MAT-002",
        senha_hash="$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        centro_custo_id=cc.id,
    )
    col.nome = "Maria Souza"
    col.email = "maria@example.com"
    db_session.add(col)
    await db_session.flush()
    db_session.expire(col)

    fetched = (
        await db_session.execute(
            select(ColaboradorImport).where(ColaboradorImport.matricula == "MAT-002")
        )
    ).scalar_one()
    assert fetched.nome == "Maria Souza"
    assert fetched.email == "maria@example.com"


async def test_none_em_campos_opcionais(db_session: AsyncSession) -> None:
    cc = await _make_centro_custo(db_session)
    col = ColaboradorImport(
        matricula="MAT-003",
        senha_hash="$2b$12$yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
        centro_custo_id=cc.id,
    )
    # Nada atribuído — nome_enc e email_enc devem ficar None
    db_session.add(col)
    await db_session.flush()

    assert col.nome_enc is None
    assert col.email_enc is None
    assert col.nome is None
    assert col.email is None


async def test_setar_para_none_zera_campo_cifrado(db_session: AsyncSession) -> None:
    cc = await _make_centro_custo(db_session)
    col = ColaboradorImport(
        matricula="MAT-004",
        senha_hash="$2b$12$zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        centro_custo_id=cc.id,
    )
    col.nome = "Temporário"
    db_session.add(col)
    await db_session.flush()
    assert col.nome_enc is not None

    col.nome = None
    await db_session.flush()
    assert col.nome_enc is None
    assert col.nome is None


async def test_inserts_seguidos_geram_ciphertext_distinto(
    db_session: AsyncSession,
) -> None:
    """Nonces aleatórios devem produzir ciphertext distinto para o mesmo plaintext."""
    cc = await _make_centro_custo(db_session)
    col_a = ColaboradorImport(
        matricula="MAT-005a",
        senha_hash="$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        centro_custo_id=cc.id,
    )
    col_b = ColaboradorImport(
        matricula="MAT-005b",
        senha_hash="$2b$12$bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        centro_custo_id=cc.id,
    )
    col_a.nome = "Mesmo Nome"
    col_b.nome = "Mesmo Nome"
    db_session.add_all([col_a, col_b])
    await db_session.flush()

    assert col_a.nome_enc != col_b.nome_enc
    assert col_a.nome == col_b.nome == "Mesmo Nome"

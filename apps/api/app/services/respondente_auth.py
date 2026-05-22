"""Autenticação do respondente — Sprint 2 #7.

Lookup O(1) por HMAC-SHA256 determinístico da senha (coluna `credencial.senha_hmac`).
Verificação primária por argon2id (`credencial.senha_hash`). Token de sessão
opaco (UUID) emitido na 1ª autenticação; logins subsequentes dentro da janela
de 48h devolvem o MESMO token (idempotência → totem PWA pode reabrir o
questionário se a aba cair).

Importante: o `code` `senha_invalida` é o mesmo para "senha inexistente" e
"hmac existe mas argon2id não bate" — evita confirmação parcial via timing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_sha256
from app.core.security import verify_senha
from app.models.operacional import Credencial

SESSAO_RESPONDENTE_TTL = timedelta(hours=48)


class RespondenteAuthError(Exception):
    """Falha controlada na auth do respondente. `code` é estável."""

    def __init__(self, code: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.code = code
        self.mensagem = mensagem


@dataclass
class RespondenteSessao:
    credencial: Credencial
    token: uuid.UUID
    expira_em: datetime


async def login_respondente(db: AsyncSession, *, senha: str) -> RespondenteSessao:
    """Localiza credencial via HMAC + verifica argon2id + emite/reusa token."""
    senha = senha.strip()
    if not senha:
        raise RespondenteAuthError("senha_invalida", "Senha inválida.")

    hmac_lookup = hmac_sha256(senha)
    cred = (
        await db.execute(select(Credencial).where(Credencial.senha_hmac == hmac_lookup))
    ).scalar_one_or_none()

    if cred is None or not verify_senha(senha, cred.senha_hash):
        # Mesmo code para "não existe" e "argon2id não bate".
        raise RespondenteAuthError("senha_invalida", "Senha inválida.")

    agora = datetime.now(timezone.utc)

    # Idempotência dentro da janela de 48h: reaproveita token se ainda válido.
    if (
        cred.token_sessao_temporario is not None
        and cred.expira_em is not None
        and cred.expira_em > agora
    ):
        return RespondenteSessao(
            credencial=cred,
            token=cred.token_sessao_temporario,
            expira_em=cred.expira_em,
        )

    # Emissão nova: 1ª autenticação OU sessão anterior expirada.
    token = uuid.uuid4()
    cred.token_sessao_temporario = token
    cred.consumida_em = agora if cred.consumida_em is None else cred.consumida_em
    cred.expira_em = agora + SESSAO_RESPONDENTE_TTL
    await db.flush()
    await db.commit()
    return RespondenteSessao(credencial=cred, token=token, expira_em=cred.expira_em)


async def carregar_credencial_por_token(
    db: AsyncSession, *, token: uuid.UUID
) -> Credencial:
    """Resolve o cookie do respondente para a Credencial ativa."""
    cred = (
        await db.execute(
            select(Credencial).where(Credencial.token_sessao_temporario == token)
        )
    ).scalar_one_or_none()
    if cred is None:
        raise RespondenteAuthError(
            "sessao_respondente_invalida", "Sessão de respondente inválida."
        )
    if cred.expira_em is None or cred.expira_em <= datetime.now(timezone.utc):
        raise RespondenteAuthError(
            "sessao_respondente_expirada", "Sessão de respondente expirada."
        )
    return cred

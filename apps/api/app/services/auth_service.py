"""Service de autenticação do operador.

Concentra regras de senha, sessão (cookie ↔ DB), TOTP e auditoria. Endpoints
em `app.api.v1.auth` apenas orquestram chamadas daqui — sem regra de negócio.

Estados de sessão:
    pendente_totp → ativa → revogada
    pendente_totp expira em PENDENTE_TOTP_TTL (5 min)
    ativa expira em SESSAO_ATIVA_TTL (8 horas)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    hash_senha,
    hash_token_sessao,
    novo_token_sessao,
    novo_totp_secret,
    precisa_rehash,
    totp_provisioning_uri,
    verifica_totp,
    verify_senha,
)
from app.models._base import SessaoAdminEstado
from app.models.operacional import Auditoria, Operador, SessaoAdmin

PENDENTE_TOTP_TTL = timedelta(minutes=5)
SESSAO_ATIVA_TTL = timedelta(hours=8)


class AuthError(Exception):
    """Falha controlada de autenticação. `code` é estável para o front."""

    def __init__(self, code: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.code = code
        self.mensagem = mensagem


@dataclass
class LoginResultado:
    operador: Operador
    token_sessao: str
    sessao: SessaoAdmin
    totp_pendente: bool


async def registrar_audit(
    db: AsyncSession,
    *,
    usuario: str,
    acao: str,
    recurso: str,
    meta: dict[str, Any] | None = None,
) -> None:
    entry = Auditoria(usuario=usuario, acao=acao, recurso=recurso, meta=meta)
    db.add(entry)
    await db.flush()


async def _criar_sessao(
    db: AsyncSession,
    *,
    operador: Operador,
    estado: SessaoAdminEstado,
    ttl: timedelta,
    ip_origem: str | None,
    user_agent: str | None,
) -> tuple[SessaoAdmin, str]:
    token = novo_token_sessao()
    agora = datetime.now(timezone.utc)
    sessao = SessaoAdmin(
        operador_id=operador.id,
        token_hash=hash_token_sessao(token),
        estado=estado,
        expira_em=agora + ttl,
        ip_origem=ip_origem,
        user_agent=user_agent,
    )
    db.add(sessao)
    await db.flush()
    return sessao, token


async def login(
    db: AsyncSession,
    *,
    email: str,
    senha: str,
    ip_origem: str | None = None,
    user_agent: str | None = None,
) -> LoginResultado:
    """Verifica senha e cria sessão (pendente_totp se totp_enabled, senão ativa)."""
    op = (
        await db.execute(select(Operador).where(Operador.email == email))
    ).scalar_one_or_none()

    if op is None:
        await registrar_audit(
            db,
            usuario=email,
            acao="login_falhou",
            recurso="operadores",
            meta={"motivo": "operador_inexistente"},
        )
        await db.commit()
        raise AuthError("credenciais_invalidas", "Credenciais inválidas.")

    if not op.ativo:
        await registrar_audit(
            db,
            usuario=email,
            acao="login_falhou",
            recurso="operadores",
            meta={"motivo": "operador_inativo", "operador_id": str(op.id)},
        )
        await db.commit()
        raise AuthError("operador_inativo", "Operador inativo.")

    if not verify_senha(senha, op.senha_hash):
        await registrar_audit(
            db,
            usuario=email,
            acao="login_falhou",
            recurso="operadores",
            meta={"motivo": "senha_incorreta", "operador_id": str(op.id)},
        )
        await db.commit()
        raise AuthError("credenciais_invalidas", "Credenciais inválidas.")

    if precisa_rehash(op.senha_hash):
        op.senha_hash = hash_senha(senha)
        await db.flush()

    if op.totp_enabled:
        sessao, token = await _criar_sessao(
            db,
            operador=op,
            estado=SessaoAdminEstado.pendente_totp,
            ttl=PENDENTE_TOTP_TTL,
            ip_origem=ip_origem,
            user_agent=user_agent,
        )
        await registrar_audit(
            db,
            usuario=email,
            acao="login_senha_ok",
            recurso="sessao_admin",
            meta={"sessao_id": str(sessao.id), "estado": "pendente_totp"},
        )
        await db.commit()
        return LoginResultado(operador=op, token_sessao=token, sessao=sessao, totp_pendente=True)

    sessao, token = await _criar_sessao(
        db,
        operador=op,
        estado=SessaoAdminEstado.ativa,
        ttl=SESSAO_ATIVA_TTL,
        ip_origem=ip_origem,
        user_agent=user_agent,
    )
    await registrar_audit(
        db,
        usuario=email,
        acao="login_sucesso",
        recurso="sessao_admin",
        meta={"sessao_id": str(sessao.id)},
    )
    await db.commit()
    return LoginResultado(operador=op, token_sessao=token, sessao=sessao, totp_pendente=False)


async def _carregar_sessao(
    db: AsyncSession,
    *,
    token: str,
    estado_esperado: SessaoAdminEstado,
) -> tuple[Operador, SessaoAdmin]:
    """Lookup por token_hash, validando estado e expiração."""
    token_hash = hash_token_sessao(token)
    sessao = (
        await db.execute(select(SessaoAdmin).where(SessaoAdmin.token_hash == token_hash))
    ).scalar_one_or_none()
    if sessao is None:
        raise AuthError("sessao_invalida", "Sessão inválida.")
    if sessao.estado != estado_esperado:
        raise AuthError("sessao_estado_invalido", "Estado de sessão inválido.")
    if sessao.revogada_em is not None:
        raise AuthError("sessao_revogada", "Sessão revogada.")
    if sessao.expira_em <= datetime.now(timezone.utc):
        raise AuthError("sessao_expirada", "Sessão expirada.")
    op = (
        await db.execute(select(Operador).where(Operador.id == sessao.operador_id))
    ).scalar_one()
    if not op.ativo:
        raise AuthError("operador_inativo", "Operador inativo.")
    return op, sessao


async def carregar_operador_ativo(db: AsyncSession, *, token: str) -> Operador:
    op, _ = await _carregar_sessao(db, token=token, estado_esperado=SessaoAdminEstado.ativa)
    return op


async def verificar_totp_login(
    db: AsyncSession,
    *,
    token: str,
    codigo: str,
) -> LoginResultado:
    """Transiciona sessão pendente_totp → ativa após validar código."""
    op, sessao = await _carregar_sessao(
        db, token=token, estado_esperado=SessaoAdminEstado.pendente_totp
    )
    if op.totp_secret is None or not verifica_totp(op.totp_secret, codigo):
        await registrar_audit(
            db,
            usuario=op.email,
            acao="totp_falhou",
            recurso="sessao_admin",
            meta={"sessao_id": str(sessao.id)},
        )
        await db.commit()
        raise AuthError("totp_invalido", "Código TOTP inválido.")
    sessao.estado = SessaoAdminEstado.ativa
    sessao.expira_em = datetime.now(timezone.utc) + SESSAO_ATIVA_TTL
    await db.flush()
    await registrar_audit(
        db,
        usuario=op.email,
        acao="totp_sucesso",
        recurso="sessao_admin",
        meta={"sessao_id": str(sessao.id)},
    )
    await db.commit()
    return LoginResultado(operador=op, token_sessao=token, sessao=sessao, totp_pendente=False)


async def logout(db: AsyncSession, *, token: str) -> None:
    """Revoga a sessão (idempotente — silenciosa se token desconhecido)."""
    token_hash = hash_token_sessao(token)
    sessao = (
        await db.execute(select(SessaoAdmin).where(SessaoAdmin.token_hash == token_hash))
    ).scalar_one_or_none()
    if sessao is None or sessao.estado == SessaoAdminEstado.revogada:
        return
    sessao.estado = SessaoAdminEstado.revogada
    sessao.revogada_em = datetime.now(timezone.utc)
    await db.flush()
    op = (
        await db.execute(select(Operador).where(Operador.id == sessao.operador_id))
    ).scalar_one_or_none()
    await registrar_audit(
        db,
        usuario=op.email if op else "(desconhecido)",
        acao="logout",
        recurso="sessao_admin",
        meta={"sessao_id": str(sessao.id)},
    )
    await db.commit()


async def setup_totp(db: AsyncSession, *, operador: Operador) -> tuple[str, str]:
    """Gera novo secret TOTP, salva sem habilitar; retorna (secret, provisioning_uri)."""
    secret = novo_totp_secret()
    operador.totp_secret = secret
    operador.totp_enabled = False
    await db.flush()
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="totp_setup",
        recurso="operadores",
        meta={"operador_id": str(operador.id)},
    )
    await db.commit()
    return secret, totp_provisioning_uri(secret, operador.email)


async def confirmar_totp(
    db: AsyncSession,
    *,
    operador: Operador,
    codigo: str,
) -> None:
    """Habilita TOTP após validar o primeiro código gerado pelo app."""
    if operador.totp_secret is None:
        raise AuthError("totp_nao_configurado", "TOTP não foi configurado.")
    if not verifica_totp(operador.totp_secret, codigo):
        await registrar_audit(
            db,
            usuario=operador.email,
            acao="totp_confirm_falhou",
            recurso="operadores",
            meta={"operador_id": str(operador.id)},
        )
        await db.commit()
        raise AuthError("totp_invalido", "Código TOTP inválido.")
    operador.totp_enabled = True
    await db.flush()
    await registrar_audit(
        db,
        usuario=operador.email,
        acao="totp_confirm_ok",
        recurso="operadores",
        meta={"operador_id": str(operador.id)},
    )
    await db.commit()


async def criar_operador(
    db: AsyncSession,
    *,
    email: str,
    senha: str,
    nome: str | None = None,
    sobrenome: str | None = None,
) -> Operador:
    """Bootstrap de operador — usado pelo CLI e por endpoints futuros de gestão."""
    existente = (
        await db.execute(select(Operador).where(Operador.email == email))
    ).scalar_one_or_none()
    if existente is not None:
        raise AuthError("email_em_uso", f"Já existe operador com o email {email}.")
    op = Operador(email=email, senha_hash=hash_senha(senha))
    if nome is not None:
        op.nome = nome
    if sobrenome is not None:
        op.sobrenome = sobrenome
    db.add(op)
    await db.flush()
    await registrar_audit(
        db,
        usuario=email,
        acao="operador_criado",
        recurso="operadores",
        meta={"operador_id": str(op.id)},
    )
    await db.commit()
    return op


def operador_dict(op: Operador) -> dict[str, Any]:
    """Serialização auxiliar para o OperadorOut do schemas."""
    return {
        "id": op.id,
        "email": op.email,
        "nome": op.nome,
        "sobrenome": op.sobrenome,
        "totp_enabled": op.totp_enabled,
        "ativo": op.ativo,
        "criado_em": op.criado_em,
    }

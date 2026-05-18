"""Tabelas operacionais — §7.2 da documentação técnica.

`colaborador_import` é isolada e REMOVIDA do prod após a distribuição das senhas.
`credencial` faz ponte apenas com `centros_custo`, nunca com `colaborador_import`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt, encrypt
from app.core.database import Base
from app.models._base import (
    LembreteStatus,
    LembreteTipo,
    SessaoAdminEstado,
    StatusDistribuicao,
    UUIDPKMixin,
)


class ColaboradorImport(Base):
    """Tabela isolada — sem FK partilhada com `respostas`. Descartada pós-distribuição.

    Campos PII (`nome`, `email`) são persistidos cifrados em colunas `*_enc`
    via AES-256-GCM (ver `app.core.crypto`). Acesso transparente via properties.
    """

    __tablename__ = "colaborador_import"

    matricula: Mapped[str] = mapped_column(String(60), primary_key=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    centro_custo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("centros_custo.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status_distribuicao: Mapped[StatusDistribuicao] = mapped_column(
        ENUM(StatusDistribuicao, name="status_distribuicao"),
        nullable=False,
        server_default=StatusDistribuicao.pendente.value,
    )
    nome_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    @property
    def nome(self) -> str | None:
        return decrypt(self.nome_enc) if self.nome_enc is not None else None

    @nome.setter
    def nome(self, value: str | None) -> None:
        self.nome_enc = encrypt(value) if value is not None else None

    @property
    def email(self) -> str | None:
        return decrypt(self.email_enc) if self.email_enc is not None else None

    @email.setter
    def email(self, value: str | None) -> None:
        self.email_enc = encrypt(value) if value is not None else None


class Credencial(Base):
    __tablename__ = "credencial"

    senha_hash: Mapped[str] = mapped_column(String(255), primary_key=True)
    centro_custo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("centros_custo.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    consumida_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # TTL 48h — emitido na primeira autenticação
    token_sessao_temporario: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True
    )


class Lembrete(UUIDPKMixin, Base):
    """Engajamento — disparos em D+3, D+7, D+15, D+30."""

    __tablename__ = "lembretes"

    # FK válida apenas durante a janela de distribuição (colaborador_import existe)
    matricula: Mapped[str] = mapped_column(
        ForeignKey("colaborador_import.matricula", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo: Mapped[LembreteTipo] = mapped_column(
        ENUM(LembreteTipo, name="lembrete_tipo"), nullable=False
    )
    enviado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[LembreteStatus] = mapped_column(
        ENUM(LembreteStatus, name="lembrete_status"),
        nullable=False,
        server_default=LembreteStatus.pendente.value,
    )


class Auditoria(UUIDPKMixin, Base):
    """Trilha de auditoria — exigência da cláusula 22 do contrato HCPA."""

    __tablename__ = "auditoria"

    usuario: Mapped[str] = mapped_column(String(120), nullable=False)
    acao: Mapped[str] = mapped_column(String(120), nullable=False)
    recurso: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class Operador(UUIDPKMixin, Base):
    """Operador HMind do painel admin.

    Senha em argon2id; TOTP secret e PII (nome, sobrenome) cifrados via
    `app.core.crypto`. `ativo=false` bloqueia login sem apagar o registro
    (preserva trilha de auditoria).
    """

    __tablename__ = "operadores"

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    nome_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    sobrenome_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    @property
    def totp_secret(self) -> str | None:
        return decrypt(self.totp_secret_enc) if self.totp_secret_enc is not None else None

    @totp_secret.setter
    def totp_secret(self, value: str | None) -> None:
        self.totp_secret_enc = encrypt(value) if value is not None else None

    @property
    def nome(self) -> str | None:
        return decrypt(self.nome_enc) if self.nome_enc is not None else None

    @nome.setter
    def nome(self, value: str | None) -> None:
        self.nome_enc = encrypt(value) if value is not None else None

    @property
    def sobrenome(self) -> str | None:
        return decrypt(self.sobrenome_enc) if self.sobrenome_enc is not None else None

    @sobrenome.setter
    def sobrenome(self, value: str | None) -> None:
        self.sobrenome_enc = encrypt(value) if value is not None else None


class SessaoAdmin(UUIDPKMixin, Base):
    """Sessão de operador no painel admin.

    Cookie contém o token opaco; banco guarda apenas SHA-256 (`token_hash`).
    Estado `pendente_totp` cobre a janela entre verificar senha e validar TOTP.
    """

    __tablename__ = "sessao_admin"

    operador_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operadores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True
    )
    estado: Mapped[SessaoAdminEstado] = mapped_column(
        ENUM(SessaoAdminEstado, name="sessao_admin_estado"),
        nullable=False,
        server_default=SessaoAdminEstado.ativa.value,
    )
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expira_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revogada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip_origem: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

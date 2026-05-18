"""Tabelas core — §7.1 da documentação técnica.

Caminho de query a partir de uma resposta termina sem identidade:
respostas → questionarios → centros_custo. Nenhuma FK alcança colaborador_import.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._base import QuestionarioStatus, UUIDPKMixin


class Dominio(UUIDPKMixin, Base):
    __tablename__ = "dominios"

    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    # 1 = quanto maior melhor, -1 = quanto maior pior
    polaridade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    ordem_apresentacao: Mapped[int] = mapped_column(Integer, nullable=False)

    itens: Mapped[list["Item"]] = relationship(back_populates="dominio")

    __table_args__ = (
        CheckConstraint("polaridade IN (-1, 1)", name="ck_dominios_polaridade"),
    )


class Item(UUIDPKMixin, Base):
    __tablename__ = "itens"

    dominio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dominios.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    texto_pergunta: Mapped[str] = mapped_column(Text, nullable=False)
    ordem_apresentacao: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'A' frequência ou 'B' intensidade
    escala_tipo: Mapped[str] = mapped_column(String(1), nullable=False)
    # true para itens com escala invertida no instrumento oficial
    invertido: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    dominio: Mapped["Dominio"] = relationship(back_populates="itens")

    __table_args__ = (
        CheckConstraint("escala_tipo IN ('A', 'B')", name="ck_itens_escala_tipo"),
    )


class CentroCusto(UUIDPKMixin, Base):
    __tablename__ = "centros_custo"

    codigo: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    # granularidade superior usada quando k < 5
    bloco_predio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    centro_custo_pai_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("centros_custo.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    total_colaboradores: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    pai: Mapped["CentroCusto | None"] = relationship(
        back_populates="filhos", remote_side="CentroCusto.id"
    )
    filhos: Mapped[list["CentroCusto"]] = relationship(back_populates="pai")


class Questionario(UUIDPKMixin, Base):
    """Granularidade condicional (k-anonimato em repouso):
    para CCs com < K_ANONIMATO_MIN colaboradores, gravamos apenas `bloco_predio`
    e zeramos `centro_custo_id`. Exatamente um dos dois é preenchido por linha.
    Use `app.services.questionario_service.criar_questionario` em vez de
    instanciar diretamente.
    """

    __tablename__ = "questionarios"

    # descorrelacionado da identidade do respondente
    token_anonimo: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    centro_custo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("centros_custo.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # preenchido quando o CC é pequeno demais para granularidade fina
    bloco_predio: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    data_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    data_conclusao: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[QuestionarioStatus] = mapped_column(
        ENUM(QuestionarioStatus, name="questionario_status"),
        nullable=False,
        server_default=QuestionarioStatus.iniciado.value,
    )

    respostas: Mapped[list["Resposta"]] = relationship(back_populates="questionario")

    __table_args__ = (
        CheckConstraint(
            "(centro_custo_id IS NULL) <> (bloco_predio IS NULL)",
            name="ck_questionarios_granularidade_xor",
        ),
    )


class Resposta(UUIDPKMixin, Base):
    __tablename__ = "respostas"

    questionario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questionarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("itens.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    valor: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # arredondado para janela de hora — não revelar timing fino do respondente
    submetida_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    questionario: Mapped["Questionario"] = relationship(back_populates="respostas")
    item: Mapped["Item"] = relationship()

    __table_args__ = (
        CheckConstraint("valor BETWEEN 0 AND 4", name="ck_respostas_valor"),
    )

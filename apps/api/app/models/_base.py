import enum
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    """PK UUID gerada no banco via pgcrypto (`gen_random_uuid()`)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class QuestionarioStatus(str, enum.Enum):
    iniciado = "iniciado"
    concluido = "concluido"
    abandonado = "abandonado"


class StatusDistribuicao(str, enum.Enum):
    pendente = "pendente"
    distribuida = "distribuida"
    confirmada = "confirmada"


class LembreteTipo(str, enum.Enum):
    email = "email"
    sms = "sms"


class LembreteStatus(str, enum.Enum):
    pendente = "pendente"
    enviado = "enviado"
    falhou = "falhou"

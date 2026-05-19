"""Integration tests da submissão pública de respostas via token_anonimo.

Cobre caminho feliz em CC grande e CC pequeno (granularidade bloco_predio),
idempotência (segunda submissão falha), token desconhecido, item inválido,
itens duplicados, valor fora do intervalo, payload vazio, e o arredondamento
para a hora dos timestamps gravados.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import QuestionarioStatus
from app.models.core import CentroCusto, Dominio, Item, Resposta
from app.services.questionario_service import criar_questionario


async def _cc(db: AsyncSession, *, total: int, bloco: str | None = "Bloco A") -> CentroCusto:
    cc = CentroCusto(
        codigo=f"CC-{uuid.uuid4().hex[:8]}",
        nome="CC teste",
        bloco_predio=bloco,
        total_colaboradores=total,
    )
    db.add(cc)
    await db.flush()
    return cc


async def _itens(db: AsyncSession, *, n: int = 3) -> list[Item]:
    dominio = Dominio(nome="Demandas no trabalho", polaridade=-1, ordem_apresentacao=1)
    db.add(dominio)
    await db.flush()
    itens = [
        Item(
            dominio_id=dominio.id,
            texto_pergunta=f"Pergunta {i}?",
            ordem_apresentacao=i,
            escala_tipo="A",
            invertido=False,
        )
        for i in range(n)
    ]
    db.add_all(itens)
    await db.flush()
    return itens


def _payload(itens: list[Item]) -> dict:
    return {"respostas": [{"item_id": str(i.id), "valor": idx % 5} for idx, i in enumerate(itens)]}


async def test_submissao_ok_cc_grande(client: AsyncClient, db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=42)
    q = await criar_questionario(db_session, centro_custo=cc)
    itens = await _itens(db_session, n=3)

    r = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=_payload(itens))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["questionario_id"] == str(q.id)
    assert body["total_respostas"] == 3

    await db_session.refresh(q)
    assert q.status == QuestionarioStatus.concluido
    assert q.data_conclusao is not None

    rs = (
        (await db_session.execute(select(Resposta).where(Resposta.questionario_id == q.id)))
        .scalars()
        .all()
    )
    assert len(rs) == 3
    for r_db in rs:
        # arredondado para a hora — defesa contra timing-correlação
        assert r_db.submetida_em.minute == 0
        assert r_db.submetida_em.second == 0
        assert r_db.submetida_em.microsecond == 0


async def test_submissao_ok_cc_pequeno_preserva_granularidade_bloco(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=2, bloco="Bloco X")
    q = await criar_questionario(db_session, centro_custo=cc)
    itens = await _itens(db_session, n=2)

    r = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=_payload(itens))
    assert r.status_code == 201, r.text

    await db_session.refresh(q)
    assert q.centro_custo_id is None
    assert q.bloco_predio == "Bloco X"
    assert q.status == QuestionarioStatus.concluido


async def test_segunda_submissao_devolve_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=10)
    q = await criar_questionario(db_session, centro_custo=cc)
    itens = await _itens(db_session, n=1)
    payload = _payload(itens)

    r1 = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=payload)
    assert r1.status_code == 201

    r2 = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=payload)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "questionario_ja_concluido"


async def test_token_invalido_devolve_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    itens = await _itens(db_session, n=1)
    r = await client.post(
        f"/v1/questionarios/{uuid.uuid4()}/respostas", json=_payload(itens)
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "token_invalido"


async def test_item_inexistente_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=10)
    q = await criar_questionario(db_session, centro_custo=cc)
    payload = {"respostas": [{"item_id": str(uuid.uuid4()), "valor": 2}]}
    r = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=payload)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "item_invalido"


async def test_itens_duplicados_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=10)
    q = await criar_questionario(db_session, centro_custo=cc)
    itens = await _itens(db_session, n=1)
    payload = {
        "respostas": [
            {"item_id": str(itens[0].id), "valor": 1},
            {"item_id": str(itens[0].id), "valor": 2},
        ]
    }
    r = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=payload)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "itens_duplicados"


async def test_valor_fora_do_intervalo_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=10)
    q = await criar_questionario(db_session, centro_custo=cc)
    itens = await _itens(db_session, n=1)
    payload = {"respostas": [{"item_id": str(itens[0].id), "valor": 7}]}
    r = await client.post(f"/v1/questionarios/{q.token_anonimo}/respostas", json=payload)
    assert r.status_code == 422  # pydantic ValidationError


async def test_payload_vazio_devolve_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cc = await _cc(db_session, total=10)
    q = await criar_questionario(db_session, centro_custo=cc)
    r = await client.post(
        f"/v1/questionarios/{q.token_anonimo}/respostas", json={"respostas": []}
    )
    assert r.status_code == 422  # pydantic min_length=1

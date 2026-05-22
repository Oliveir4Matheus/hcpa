"""Integration tests do endpoint agregado de respostas (operador autenticado).

Cobre as duas buckets (CC grande → centro_custo, CC pequeno → bloco_predio),
o invariante de k-anonimato em consulta (suprime quando N < 5), os erros
estáveis (CC inexistente, granularidade indisponível) e o gate de
autenticação.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto, Dominio, Item
from app.schemas.resposta import RespostaIn
from app.services import auth_service
from app.services.questionario_service import K_ANONIMATO_MIN, criar_questionario
from app.services.resposta_service import submeter_respostas

COOKIE = "hcpa_admin_sessao"
SENHA = "senha-forte-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {COOKIE: r.cookies[COOKIE]}


async def _cc(
    db: AsyncSession, *, total: int, bloco: str | None = "Bloco A", codigo: str | None = None
) -> CentroCusto:
    cc = CentroCusto(
        codigo=codigo or f"CC-{uuid.uuid4().hex[:8]}",
        nome="CC teste",
        bloco_predio=bloco,
        total_colaboradores=total,
    )
    db.add(cc)
    await db.flush()
    return cc


async def _dominio(db: AsyncSession, *, nome: str, ordem: int) -> Dominio:
    d = Dominio(nome=nome, polaridade=-1, ordem_apresentacao=ordem)
    db.add(d)
    await db.flush()
    return d


async def _item(db: AsyncSession, *, dominio: Dominio, ordem: int) -> Item:
    it = Item(
        dominio_id=dominio.id,
        texto_pergunta=f"Pergunta {ordem}?",
        ordem_apresentacao=ordem,
        escala_tipo="A",
        invertido=False,
    )
    db.add(it)
    await db.flush()
    return it


async def _seed_questionarios(
    db: AsyncSession,
    *,
    cc: CentroCusto,
    itens: list[Item],
    n: int,
    valor: int = 2,
) -> None:
    """Cria `n` questionários concluídos para `cc` respondendo `itens` com `valor`."""
    for _ in range(n):
        q = await criar_questionario(db, centro_custo=cc)
        await submeter_respostas(
            db,
            token_anonimo=q.token_anonimo,
            respostas=[RespostaIn(item_id=it.id, valor=valor) for it in itens],
        )


async def test_agregado_cc_grande_retorna_por_dominio(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="op1@example.com")
    cc = await _cc(db_session, total=20)
    d1 = await _dominio(db_session, nome="Demandas", ordem=1)
    d2 = await _dominio(db_session, nome="Apoio social", ordem=2)
    itens = [
        await _item(db_session, dominio=d1, ordem=1),
        await _item(db_session, dominio=d1, ordem=2),
        await _item(db_session, dominio=d2, ordem=3),
    ]
    await _seed_questionarios(db_session, cc=cc, itens=itens, n=K_ANONIMATO_MIN, valor=3)

    r = await client.get(
        "/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)}, cookies=cookies
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bucket"] == {"tipo": "centro_custo", "valor": cc.codigo}
    assert body["n_questionarios"] == K_ANONIMATO_MIN
    assert body["supressao"] is None
    nomes = {d["dominio_nome"]: d for d in body["por_dominio"]}
    assert set(nomes) == {"Demandas", "Apoio social"}
    # 5 questionários × 2 itens em "Demandas" × valor 3
    assert nomes["Demandas"]["n_respostas"] == 10
    assert nomes["Demandas"]["media_valor"] == 3.0
    assert nomes["Apoio social"]["n_respostas"] == 5
    # ordem segue ordem_apresentacao do domínio
    assert [d["dominio_nome"] for d in body["por_dominio"]] == ["Demandas", "Apoio social"]


async def test_agregado_cc_pequeno_agrega_no_bloco_predio(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Dois CCs pequenos no mesmo bloco somam para superar o k-anonimato."""
    cookies = await _login(client, db_session, email="op2@example.com")
    cc_a = await _cc(db_session, total=2, bloco="Bloco X", codigo="CC-A")
    cc_b = await _cc(db_session, total=3, bloco="Bloco X", codigo="CC-B")
    d = await _dominio(db_session, nome="Demandas", ordem=1)
    it = await _item(db_session, dominio=d, ordem=1)

    await _seed_questionarios(db_session, cc=cc_a, itens=[it], n=2, valor=4)
    await _seed_questionarios(db_session, cc=cc_b, itens=[it], n=3, valor=4)

    # qualquer dos dois CCs deve resolver para a mesma bucket Bloco X com N=5
    for cc in (cc_a, cc_b):
        r = await client.get(
            "/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)}, cookies=cookies
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["bucket"] == {"tipo": "bloco_predio", "valor": "Bloco X"}
        assert body["n_questionarios"] == 5
        assert body["supressao"] is None
        assert body["por_dominio"][0]["media_valor"] == 4.0


async def test_agregado_supressao_quando_n_menor_que_5(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="op3@example.com")
    cc = await _cc(db_session, total=10)
    d = await _dominio(db_session, nome="Demandas", ordem=1)
    it = await _item(db_session, dominio=d, ordem=1)
    await _seed_questionarios(db_session, cc=cc, itens=[it], n=3)

    r = await client.get(
        "/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)}, cookies=cookies
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_questionarios"] == 3
    assert body["por_dominio"] == []
    assert body["supressao"] == {
        "motivo": "k_anonimato_insuficiente",
        "minimo_requerido": K_ANONIMATO_MIN,
        "n_atual": 3,
    }


async def test_agregado_sem_questionarios_concluidos(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="op4@example.com")
    cc = await _cc(db_session, total=10)
    r = await client.get(
        "/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)}, cookies=cookies
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_questionarios"] == 0
    assert body["supressao"]["n_atual"] == 0


async def test_agregado_cc_inexistente_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="op5@example.com")
    r = await client.get(
        "/v1/respostas/agregado", params={"centro_custo_id": str(uuid.uuid4())}, cookies=cookies
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "centro_custo_invalido"


async def test_agregado_cc_pequeno_sem_bloco_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="op6@example.com")
    cc = await _cc(db_session, total=2, bloco=None)
    r = await client.get(
        "/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)}, cookies=cookies
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "granularidade_indisponivel"


async def test_agregado_sem_auth_401(client: AsyncClient, db_session: AsyncSession) -> None:
    cc = await _cc(db_session, total=10)
    r = await client.get("/v1/respostas/agregado", params={"centro_custo_id": str(cc.id)})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_ausente"

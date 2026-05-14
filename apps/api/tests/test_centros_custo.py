from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto

PREVIEW = "/v1/centros-custo/import/preview"
COMMIT = "/v1/centros-custo/import/commit"


async def test_preview_classifica_novos(client: AsyncClient) -> None:
    payload = {
        "itens": [
            {"codigo": "PREDIO-A", "nome": "Prédio A"},
            {"codigo": "SETOR-A1", "nome": "Setor A1", "codigo_pai": "PREDIO-A"},
        ]
    }
    resp = await client.post(PREVIEW, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valido"] is True
    assert set(body["novos"]) == {"PREDIO-A", "SETOR-A1"}
    assert body["atualizados"] == []


async def test_preview_detecta_codigo_pai_inexistente(client: AsyncClient) -> None:
    payload = {"itens": [{"codigo": "ORFAO", "nome": "Órfão", "codigo_pai": "NAO-EXISTE"}]}
    resp = await client.post(PREVIEW, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valido"] is False
    assert body["erros"][0]["codigo"] == "ORFAO"
    assert "não existe" in body["erros"][0]["erro"]


async def test_preview_detecta_ciclo(client: AsyncClient) -> None:
    payload = {
        "itens": [
            {"codigo": "A", "nome": "A", "codigo_pai": "B"},
            {"codigo": "B", "nome": "B", "codigo_pai": "A"},
        ]
    }
    resp = await client.post(PREVIEW, json=payload)
    body = resp.json()
    assert body["valido"] is False
    assert {e["codigo"] for e in body["erros"]} == {"A", "B"}
    assert all("ciclo" in e["erro"] for e in body["erros"])


async def test_commit_persiste_e_preserva_hierarquia(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = {
        "itens": [
            {"codigo": "PREDIO-X", "nome": "Prédio X", "total_colaboradores": 50},
            {"codigo": "SETOR-X1", "nome": "Setor X1", "codigo_pai": "PREDIO-X"},
        ]
    }
    resp = await client.post(COMMIT, json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"criados": 2, "atualizados": 0}

    rows = (
        (await db_session.execute(select(CentroCusto).order_by(CentroCusto.codigo)))
        .scalars()
        .all()
    )
    by_codigo = {cc.codigo: cc for cc in rows}
    assert by_codigo["SETOR-X1"].centro_custo_pai_id == by_codigo["PREDIO-X"].id
    assert by_codigo["PREDIO-X"].centro_custo_pai_id is None
    assert by_codigo["PREDIO-X"].total_colaboradores == 50


async def test_commit_rejeita_payload_invalido(client: AsyncClient) -> None:
    payload = {"itens": [{"codigo": "Y", "nome": "Y", "codigo_pai": "Y"}]}
    resp = await client.post(COMMIT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"]["erros"][0]["codigo"] == "Y"


async def test_commit_atualiza_existente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(COMMIT, json={"itens": [{"codigo": "UPD-1", "nome": "Nome antigo"}]})
    resp = await client.post(
        COMMIT, json={"itens": [{"codigo": "UPD-1", "nome": "Nome novo"}]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"criados": 0, "atualizados": 1}

    cc = (
        await db_session.execute(select(CentroCusto).where(CentroCusto.codigo == "UPD-1"))
    ).scalar_one()
    assert cc.nome == "Nome novo"

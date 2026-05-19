from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import CentroCusto
from app.services import auth_service

PREVIEW = "/v1/centros-custo/import/preview"
COMMIT = "/v1/centros-custo/import/commit"
LIST = "/v1/centros-custo"
COOKIE = "hcpa_admin_sessao"
SENHA = "senha-forte-1234"


async def _login(client: AsyncClient, db: AsyncSession, *, email: str) -> dict[str, str]:
    await auth_service.criar_operador(db, email=email, senha=SENHA)
    r = await client.post("/v1/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {COOKIE: r.cookies[COOKIE]}


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


async def test_list_exige_auth(client: AsyncClient) -> None:
    r = await client.get(LIST)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "sessao_ausente"


async def test_list_retorna_ccs_ordenados_por_codigo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cookies = await _login(client, db_session, email="list-op@example.com")
    # prefixo único isola estes CCs do estado pré-existente do banco de dev
    prefixo = "LST"
    db_session.add_all(
        [
            CentroCusto(codigo=f"{prefixo}-ZETA", nome="Zeta", total_colaboradores=10),
            CentroCusto(
                codigo=f"{prefixo}-ALFA",
                nome="Alfa",
                total_colaboradores=2,
                bloco_predio="Bloco 1",
            ),
            CentroCusto(codigo=f"{prefixo}-MED", nome="Med", total_colaboradores=5),
        ]
    )
    await db_session.flush()

    r = await client.get(LIST, cookies=cookies)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["itens"])

    nossos = [it for it in body["itens"] if it["codigo"].startswith(prefixo)]
    codigos = [it["codigo"] for it in nossos]
    assert codigos == [f"{prefixo}-ALFA", f"{prefixo}-MED", f"{prefixo}-ZETA"]
    alfa = nossos[0]
    assert alfa["bloco_predio"] == "Bloco 1"
    assert alfa["total_colaboradores"] == 2
    assert set(alfa.keys()) == {
        "id",
        "codigo",
        "nome",
        "bloco_predio",
        "total_colaboradores",
    }

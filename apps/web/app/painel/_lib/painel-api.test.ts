import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PainelError,
  getAgregado,
  getCentrosCusto,
  type AgregadoOut,
  type CentroCustoListOut,
} from "./painel-api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getCentrosCusto", () => {
  it("faz GET para /api/v1/centros-custo com credenciais same-origin", async () => {
    const payload: CentroCustoListOut = {
      total: 1,
      itens: [
        {
          id: "00000000-0000-0000-0000-000000000001",
          codigo: "ROOT",
          nome: "Raiz",
          bloco_predio: null,
          total_colaboradores: 0,
        },
      ],
    };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(payload), { status: 200 }),
    );

    const r = await getCentrosCusto();
    expect(r).toEqual(payload);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/v1/centros-custo");
    expect(init.credentials).toBe("same-origin");
  });

  it("em 401 lança PainelError com code 'nao_autenticado'", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("", { status: 401 }),
    );
    const erro = await getCentrosCusto().catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(PainelError);
    expect((erro as PainelError).code).toBe("nao_autenticado");
  });
});

describe("getAgregado", () => {
  it("monta a querystring centro_custo_id e devolve o agregado", async () => {
    const payload: AgregadoOut = {
      centro_custo_id: "11111111-1111-1111-1111-111111111111",
      bucket: { tipo: "centro_custo", valor: "ENF-3A" },
      n_questionarios: 9,
      por_dominio: [
        {
          dominio_id: "22222222-2222-2222-2222-222222222222",
          dominio_nome: "Exigências quantitativas",
          n_respostas: 27,
          media_valor: 2.34,
        },
      ],
      supressao: null,
    };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(payload), { status: 200 }),
    );

    const r = await getAgregado("11111111-1111-1111-1111-111111111111");
    expect(r).toEqual(payload);

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "/api/v1/respostas/agregado?centro_custo_id=11111111-1111-1111-1111-111111111111",
    );
  });

  it("em 422 com code granularidade_indisponivel, propaga PainelError com o code estável", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: {
            code: "granularidade_indisponivel",
            mensagem: "CC pequeno sem bloco_predio.",
          },
        }),
        { status: 422 },
      ),
    );
    const erro = await getAgregado(
      "33333333-3333-3333-3333-333333333333",
    ).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(PainelError);
    expect((erro as PainelError).code).toBe("granularidade_indisponivel");
    expect((erro as PainelError).message).toBe("CC pequeno sem bloco_predio.");
  });

  it("em 404 com code centro_custo_invalido, propaga o code", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { code: "centro_custo_invalido", mensagem: "CC não existe." },
        }),
        { status: 404 },
      ),
    );
    const erro = await getAgregado(
      "44444444-4444-4444-4444-444444444444",
    ).catch((e: unknown) => e);
    expect((erro as PainelError).code).toBe("centro_custo_invalido");
  });
});

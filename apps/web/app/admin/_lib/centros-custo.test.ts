import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  CentrosCustoError,
  parseCsvCentrosCusto,
  postPreview,
  postCommit,
} from "./centros-custo";

describe("parseCsvCentrosCusto", () => {
  it("parses CSV bem formado com 3 linhas", () => {
    const csv = [
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores",
      "ROOT,HCPA,,,0",
      "ADM,Administração,Prédio Central,ROOT,120",
      "ENF-3A,Enfermaria 3A,Bloco A,ROOT,85",
    ].join("\n");

    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.itens).toHaveLength(3);
    expect(r.itens[0]).toEqual({
      codigo: "ROOT",
      nome: "HCPA",
      bloco_predio: null,
      codigo_pai: null,
      total_colaboradores: 0,
    });
    expect(r.itens[1].bloco_predio).toBe("Prédio Central");
    expect(r.itens[2].total_colaboradores).toBe(85);
  });

  it("aceita CRLF (Windows line endings)", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\r\n" +
      "ROOT,HCPA,,,0\r\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.itens).toHaveLength(1);
  });

  it("aceita campos com aspas e vírgulas internas", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      'A1,"Centro, com vírgula","Bloco ""A""",,10\n';
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.itens[0].nome).toBe("Centro, com vírgula");
    expect(r.itens[0].bloco_predio).toBe('Bloco "A"');
  });

  it("ignora linhas em branco no meio do arquivo", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      "A,X,,,1\n" +
      "\n" +
      "B,Y,,,2\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.itens).toHaveLength(2);
  });

  it("rejeita cabeçalho com coluna faltando", () => {
    const csv = "codigo,nome,bloco_predio,codigo_pai\nROOT,HCPA,,\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.erros[0].mensagem).toContain("total_colaboradores");
  });

  it("rejeita arquivo vazio", () => {
    const r = parseCsvCentrosCusto("");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.erros[0].mensagem).toMatch(/vazio/i);
  });

  it("rejeita arquivo só com header (sem linhas de dados)", () => {
    const r = parseCsvCentrosCusto(
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n",
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.erros[0].mensagem).toMatch(/nenhuma linha/i);
  });

  it("rejeita total_colaboradores não-inteiro", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      "A,X,,,abc\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.erros[0].mensagem).toContain("total_colaboradores");
  });

  it("rejeita total_colaboradores negativo", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      "A,X,,,-5\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(false);
  });

  it("rejeita total_colaboradores fracionário", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      "A,X,,,1.5\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(false);
  });

  it("aceita total_colaboradores vazio como 0", () => {
    const csv =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n" +
      "A,X,,,\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.itens[0].total_colaboradores).toBe(0);
  });

  it("rejeita linha sem codigo ou sem nome", () => {
    const csvSemCodigo =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\n,X,,,0\n";
    expect(parseCsvCentrosCusto(csvSemCodigo).ok).toBe(false);

    const csvSemNome =
      "codigo,nome,bloco_predio,codigo_pai,total_colaboradores\nA,,,,0\n";
    expect(parseCsvCentrosCusto(csvSemNome).ok).toBe(false);
  });

  it("trata cabeçalho case-insensitive", () => {
    const csv =
      "CODIGO,NOME,BLOCO_PREDIO,CODIGO_PAI,TOTAL_COLABORADORES\n" +
      "A,X,,,1\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
  });

  it("trata cabeçalho com colunas fora de ordem", () => {
    const csv =
      "nome,codigo_pai,codigo,total_colaboradores,bloco_predio\n" +
      "HCPA,,ROOT,0,\n" +
      "Administração,ROOT,ADM,120,Prédio Central\n";
    const r = parseCsvCentrosCusto(csv);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.itens[0].codigo).toBe("ROOT");
    expect(r.itens[1].codigo).toBe("ADM");
    expect(r.itens[1].codigo_pai).toBe("ROOT");
    expect(r.itens[1].bloco_predio).toBe("Prédio Central");
  });
});

describe("postPreview / postCommit (com fetch mockado)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const item = {
    codigo: "ROOT",
    nome: "HCPA",
    bloco_predio: null,
    codigo_pai: null,
    total_colaboradores: 0,
  };

  it("postPreview chama proxy /api/v1/centros-custo/import/preview com same-origin", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          total: 1,
          novos: ["ROOT"],
          atualizados: [],
          erros: [],
          valido: true,
        }),
        { status: 200 },
      ),
    );

    const r = await postPreview([item]);
    expect(r.valido).toBe(true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/v1/centros-custo/import/preview");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body)).toEqual({ itens: [item] });
  });

  it("postPreview em 401 lança CentrosCustoError com code nao_autenticado", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 401 }));
    const erro = await postPreview([item]).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(CentrosCustoError);
    expect((erro as CentrosCustoError).code).toBe("nao_autenticado");
  });

  it("postPreview lança erro em HTTP não-2xx", async () => {
    fetchMock.mockResolvedValueOnce(new Response("oops", { status: 500 }));
    const erro = await postPreview([item]).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(CentrosCustoError);
    expect((erro as CentrosCustoError).message).toMatch(/HTTP 500/);
  });

  it("postCommit serializa resposta de sucesso", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ criados: 1, atualizados: 0 }), {
        status: 200,
      }),
    );
    const r = await postCommit([item]);
    expect(r).toEqual({ criados: 1, atualizados: 0 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/v1/centros-custo/import/commit");
    expect(init.credentials).toBe("same-origin");
  });

  it("postCommit em 401 lança nao_autenticado", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 401 }));
    const erro = await postCommit([item]).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(CentrosCustoError);
    expect((erro as CentrosCustoError).code).toBe("nao_autenticado");
  });

  it("postCommit propaga code payload_invalido para detail.erros do 422", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { erros: [{ codigo: "ORFAO", erro: "pai inexistente" }] },
        }),
        { status: 422 },
      ),
    );
    const erro = await postCommit([item]).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(CentrosCustoError);
    expect((erro as CentrosCustoError).code).toBe("payload_invalido");
    expect((erro as CentrosCustoError).message).toMatch(/ORFAO.*pai inexistente/);
  });
});

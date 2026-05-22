import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PainelAgregado } from "./PainelAgregado";
import type { AgregadoOut, CentroCustoOut } from "../_lib/painel-api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const centros: CentroCustoOut[] = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    codigo: "ENF-3A",
    nome: "Enfermaria 3A",
    bloco_predio: "Bloco A",
    total_colaboradores: 30,
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    codigo: "ADM",
    nome: "Administração",
    bloco_predio: null,
    total_colaboradores: 8,
  },
];

function agregadoCompleto(): AgregadoOut {
  return {
    centro_custo_id: centros[0].id,
    bucket: { tipo: "centro_custo", valor: "ENF-3A" },
    n_questionarios: 9,
    por_dominio: [
      {
        dominio_id: "aaaa-aaaa-aaaa-aaaa-aaaa00000001",
        dominio_nome: "Exigências quantitativas",
        n_respostas: 27,
        media_valor: 2.345,
      },
      {
        dominio_id: "aaaa-aaaa-aaaa-aaaa-aaaa00000002",
        dominio_nome: "Apoio social",
        n_respostas: 27,
        media_valor: 3.111,
      },
    ],
    supressao: null,
  };
}

describe("<PainelAgregado />", () => {
  it("ao escolher um CC, busca o agregado e renderiza domínios com média formatada", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(agregadoCompleto()), { status: 200 }),
    );
    const user = userEvent.setup();

    render(<PainelAgregado centros={centros} />);
    await user.selectOptions(
      screen.getByLabelText(/centro de custo/i),
      centros[0].id,
    );

    await waitFor(() => {
      expect(screen.getByText("Exigências quantitativas")).toBeInTheDocument();
    });
    expect(screen.getByText("2.35")).toBeInTheDocument();
    expect(screen.getByText("3.11")).toBeInTheDocument();
    expect(screen.getByText(/9 questionário/)).toBeInTheDocument();
    expect(
      screen.getByText(/Agregação por centro de custo/i),
    ).toBeInTheDocument();
    expect(screen.getByText("ENF-3A · Enfermaria 3A")).toBeInTheDocument();

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      `/api/v1/respostas/agregado?centro_custo_id=${centros[0].id}`,
    );
  });

  it("quando o backend devolve supressão, mostra banner k-anonimato e não lista domínios", async () => {
    const supresso: AgregadoOut = {
      centro_custo_id: centros[1].id,
      bucket: { tipo: "bloco_predio", valor: "Bloco B" },
      n_questionarios: 2,
      por_dominio: [],
      supressao: {
        motivo: "k_anonimato_insuficiente",
        minimo_requerido: 5,
        n_atual: 2,
      },
    };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(supresso), { status: 200 }),
    );
    const user = userEvent.setup();

    render(<PainelAgregado centros={centros} />);
    await user.selectOptions(
      screen.getByLabelText(/centro de custo/i),
      centros[1].id,
    );

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/k-anonimato/i);
    });
    expect(screen.getByRole("status")).toHaveTextContent(/mínimo de.*5/i);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Agregação por bloco\/prédio/i),
    ).toBeInTheDocument();
    // em bucket bloco_predio, o rótulo vem do valor (nome do bloco), não dos centros
    expect(screen.getByText("Bloco B")).toBeInTheDocument();
  });

  it("em 422 com granularidade_indisponivel, mostra o code estável no alert", async () => {
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
    const user = userEvent.setup();

    render(<PainelAgregado centros={centros} />);
    await user.selectOptions(
      screen.getByLabelText(/centro de custo/i),
      centros[1].id,
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /granularidade_indisponivel/,
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /CC pequeno sem bloco_predio/,
    );
  });
});

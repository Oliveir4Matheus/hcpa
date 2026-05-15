import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadCentrosCusto } from "./UploadCentrosCusto";

const CSV_VALIDO = [
  "codigo,nome,bloco_predio,codigo_pai,total_colaboradores",
  "ROOT,HCPA,,,0",
  "ADM,Administração,Prédio Central,ROOT,120",
  "",
].join("\n");

const CSV_PARSE_INVALIDO = "isto-nao-eh-um-csv\n";

function arquivoCsv(nome: string, conteudo: string) {
  return new File([conteudo], nome, { type: "text/csv" });
}

describe("<UploadCentrosCusto />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockPreview(body: object, status = 200) {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(body), { status }),
    );
  }

  function mockCommit(body: object, status = 200) {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(body), { status }),
    );
  }

  function inputArquivo(): HTMLInputElement {
    return screen.getByLabelText(/arquivo csv/i) as HTMLInputElement;
  }

  it("estado inicial: só seletor de arquivo aparece", () => {
    render(<UploadCentrosCusto />);
    expect(inputArquivo()).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /validar/i }),
    ).not.toBeInTheDocument();
  });

  it("CSV mal formado mostra painel de erro de parse", async () => {
    const user = userEvent.setup();
    render(<UploadCentrosCusto />);
    await user.upload(inputArquivo(), arquivoCsv("ruim.csv", CSV_PARSE_INVALIDO));

    expect(await screen.findByText(/falha ao ler o csv/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fluxo feliz: parsed → preview-ok → commit-ok", async () => {
    const user = userEvent.setup();
    mockPreview({
      total: 2,
      novos: ["ROOT", "ADM"],
      atualizados: [],
      erros: [],
      valido: true,
    });
    mockCommit({ criados: 2, atualizados: 0 });

    render(<UploadCentrosCusto />);
    await user.upload(inputArquivo(), arquivoCsv("ok.csv", CSV_VALIDO));

    expect(
      await screen.findByText(/linha\(s\) lida\(s\) do CSV/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /validar/i }));

    expect(
      await screen.findByText(/pré-visualização do import — válida/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /confirmar import/i }));

    expect(await screen.findByText(/import concluído/i)).toBeInTheDocument();
    expect(screen.getByText(/^Criados$/)).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toMatch(/\/import\/preview$/);
    expect(urls[1]).toMatch(/\/import\/commit$/);
  });

  it("preview inválido desabilita botão de commit", async () => {
    const user = userEvent.setup();
    mockPreview({
      total: 2,
      novos: [],
      atualizados: [],
      erros: [{ codigo: "ADM", erro: "código pai 'ZZZ' não existe" }],
      valido: false,
    });

    render(<UploadCentrosCusto />);
    await user.upload(inputArquivo(), arquivoCsv("ok.csv", CSV_VALIDO));
    await user.click(screen.getByRole("button", { name: /validar/i }));

    expect(
      await screen.findByText(/pré-visualização do import — inválida/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/ZZZ/)).toBeInTheDocument();

    const botaoCommit = screen.getByRole("button", {
      name: /confirmar import/i,
    });
    expect(botaoCommit).toBeDisabled();
  });

  it("falha de rede no preview mostra mensagem de erro", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValueOnce(new Error("Network down"));

    render(<UploadCentrosCusto />);
    await user.upload(inputArquivo(), arquivoCsv("ok.csv", CSV_VALIDO));
    await user.click(screen.getByRole("button", { name: /validar/i }));

    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeInTheDocument();
    });
  });

  it("idempotência: re-uploadar limpa estado e permite novo ciclo", async () => {
    const user = userEvent.setup();
    mockPreview({
      total: 2,
      novos: ["ROOT", "ADM"],
      atualizados: [],
      erros: [],
      valido: true,
    });
    mockCommit({ criados: 2, atualizados: 0 });

    render(<UploadCentrosCusto />);
    await user.upload(inputArquivo(), arquivoCsv("ok.csv", CSV_VALIDO));
    await user.click(screen.getByRole("button", { name: /validar/i }));
    await user.click(screen.getByRole("button", { name: /confirmar import/i }));
    expect(await screen.findByText(/import concluído/i)).toBeInTheDocument();

    await user.click(screen.getByText(/carregar outro arquivo/i));

    expect(
      screen.queryByRole("button", { name: /validar/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/import concluído/i)).not.toBeInTheDocument();
  });
});

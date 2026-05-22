import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TotpForm } from "./TotpForm";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("<TotpForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function respostaCompleta() {
    return new Response(
      JSON.stringify({
        totp_required: false,
        operador: {
          id: "00000000-0000-0000-0000-000000000001",
          email: "totp@example.com",
          nome: null,
          sobrenome: null,
          totp_enabled: true,
          ativo: true,
          criado_em: "2026-05-19T00:00:00Z",
        },
      }),
      { status: 200 },
    );
  }

  it("envia o código para /v1/auth/totp/verify e redireciona ao painel", async () => {
    fetchMock.mockResolvedValueOnce(respostaCompleta());
    const user = userEvent.setup();

    render(<TotpForm />);
    await user.type(screen.getByLabelText(/código TOTP/i), "123456");
    await user.click(screen.getByRole("button", { name: /verificar/i }));

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/v1/auth/totp/verify");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body)).toEqual({ codigo: "123456" });
    expect(pushMock).toHaveBeenCalledWith("/painel");
  });

  it("em totp_invalido mostra mensagem amigável e expõe o code", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { code: "totp_invalido", mensagem: "Código TOTP inválido." },
        }),
        { status: 401 },
      ),
    );
    const user = userEvent.setup();

    render(<TotpForm />);
    await user.type(screen.getByLabelText(/código TOTP/i), "000000");
    await user.click(screen.getByRole("button", { name: /verificar/i }));

    expect(pushMock).not.toHaveBeenCalled();
    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveAttribute("data-code", "totp_invalido");
    expect(alerta).toHaveTextContent(/código inválido ou expirado/i);
  });

  it("em sessao_ausente sugere refazer login", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { code: "sessao_ausente", mensagem: "Sessão ausente." },
        }),
        { status: 401 },
      ),
    );
    const user = userEvent.setup();

    render(<TotpForm />);
    await user.type(screen.getByLabelText(/código TOTP/i), "123456");
    await user.click(screen.getByRole("button", { name: /verificar/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      /sessão de login expirou. faça login novamente/i,
    );
  });
});

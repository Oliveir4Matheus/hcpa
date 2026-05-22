import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "./LoginForm";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("<LoginForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function operadorCompleto() {
    return new Response(
      JSON.stringify({
        totp_required: false,
        operador: {
          id: "00000000-0000-0000-0000-000000000001",
          email: "op@example.com",
          nome: null,
          sobrenome: null,
          totp_enabled: false,
          ativo: true,
          criado_em: "2026-05-19T00:00:00Z",
        },
      }),
      { status: 200 },
    );
  }

  it("ao logar com sucesso, redireciona para /painel", async () => {
    fetchMock.mockResolvedValueOnce(operadorCompleto());
    const user = userEvent.setup();

    render(<LoginForm />);
    await user.type(screen.getByLabelText(/e-mail/i), "op@example.com");
    await user.type(screen.getByLabelText(/senha/i), "senha-forte");
    await user.click(screen.getByRole("button", { name: /entrar/i }));

    expect(pushMock).toHaveBeenCalledWith("/painel");
  });

  it("quando o backend pede TOTP, redireciona para /login/totp com email", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ totp_required: true, email: "totp@example.com" }),
        { status: 200 },
      ),
    );
    const user = userEvent.setup();

    render(<LoginForm />);
    await user.type(screen.getByLabelText(/e-mail/i), "totp@example.com");
    await user.type(screen.getByLabelText(/senha/i), "qualquer");
    await user.click(screen.getByRole("button", { name: /entrar/i }));

    expect(pushMock).toHaveBeenCalledWith(
      "/login/totp?email=totp%40example.com",
    );
  });

  it("em 401 com code credenciais_invalidas, mostra mensagem de erro", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { code: "credenciais_invalidas", mensagem: "Credenciais inválidas." },
        }),
        { status: 401 },
      ),
    );
    const user = userEvent.setup();

    render(<LoginForm />);
    await user.type(screen.getByLabelText(/e-mail/i), "op@example.com");
    await user.type(screen.getByLabelText(/senha/i), "errada");
    await user.click(screen.getByRole("button", { name: /entrar/i }));

    expect(pushMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/credenciais inválidas/i);
  });
});

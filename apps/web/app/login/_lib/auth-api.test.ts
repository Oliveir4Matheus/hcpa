import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginError, postLogin } from "./auth-api";

describe("postLogin", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("envia POST para /api/v1/auth/login com email e senha", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
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
      ),
    );

    const r = await postLogin("op@example.com", "senha-forte");
    if (r.totp_required) throw new Error("esperava resposta completa");
    expect(r.operador.email).toBe("op@example.com");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body)).toEqual({
      email: "op@example.com",
      senha: "senha-forte",
    });
  });

  it("retorna sinalização totp_required=true quando o backend pede TOTP", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ totp_required: true, email: "totp@example.com" }),
        { status: 200 },
      ),
    );
    const r = await postLogin("totp@example.com", "x");
    expect(r.totp_required).toBe(true);
    if (r.totp_required) expect(r.email).toBe("totp@example.com");
  });

  it("lança LoginError com o code estável do backend em 401", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { code: "credenciais_invalidas", mensagem: "Credenciais inválidas." },
        }),
        { status: 401 },
      ),
    );
    await expect(postLogin("x@example.com", "errada")).rejects.toMatchObject({
      name: "LoginError",
      code: "credenciais_invalidas",
      message: "Credenciais inválidas.",
    });
  });

  it("lança LoginError com code default quando o corpo não é JSON estruturado", async () => {
    fetchMock.mockResolvedValueOnce(new Response("kaboom", { status: 500 }));
    const erro = await postLogin("x@example.com", "y").catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(LoginError);
    expect((erro as LoginError).code).toBe("erro_desconhecido");
    expect((erro as LoginError).message).toBe("HTTP 500");
  });
});

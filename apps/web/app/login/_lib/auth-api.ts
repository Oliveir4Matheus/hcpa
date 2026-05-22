/**
 * Cliente para /v1/auth/* via proxy Next (`/api/*`).
 *
 * Por que via proxy: API e Web ficam na mesma origem do ponto de vista do
 * browser, então o cookie `hcpa_admin_sessao` (SameSite=lax) é entregue em
 * fetches subsequentes sem fricção em dev.
 */

export type OperadorOut = {
  id: string;
  email: string;
  nome: string | null;
  sobrenome: string | null;
  totp_enabled: boolean;
  ativo: boolean;
  criado_em: string;
};

export type LoginRespostaCompleta = {
  totp_required: false;
  operador: OperadorOut;
};

export type LoginRespostaTotpPendente = {
  totp_required: true;
  email: string;
};

export type LoginResposta = LoginRespostaCompleta | LoginRespostaTotpPendente;

export class LoginError extends Error {
  constructor(
    public readonly code: string,
    mensagem: string,
  ) {
    super(mensagem);
    this.name = "LoginError";
  }
}

async function lerErroOuFalhar(res: Response): Promise<never> {
  let code = "erro_desconhecido";
  let mensagem = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as {
      detail?: { code?: string; mensagem?: string };
    };
    if (body.detail?.code) code = body.detail.code;
    if (body.detail?.mensagem) mensagem = body.detail.mensagem;
  } catch {
    // resposta não é JSON — mantém mensagem default
  }
  throw new LoginError(code, mensagem);
}

export async function postLogin(
  email: string,
  senha: string,
): Promise<LoginResposta> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ email, senha }),
  });
  if (!res.ok) await lerErroOuFalhar(res);
  return (await res.json()) as LoginResposta;
}

export async function postTotpVerify(
  codigo: string,
): Promise<LoginRespostaCompleta> {
  const res = await fetch("/api/v1/auth/totp/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ codigo }),
  });
  if (!res.ok) await lerErroOuFalhar(res);
  return (await res.json()) as LoginRespostaCompleta;
}

/**
 * Helpers server-side de autenticação compartilhados entre páginas RSC
 * que exigem operador autenticado (admin, painel, etc).
 *
 * O proxy `/api/*` configurado no Next só funciona para fetches do browser.
 * Aqui no server falamos diretamente com `API_URL` e repassamos o cookie
 * `hcpa_admin_sessao` lido via `next/headers`.
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export type OperadorRSC = {
  id: string;
  email: string;
  nome: string | null;
  sobrenome: string | null;
  totp_enabled: boolean;
  ativo: boolean;
  criado_em: string;
};

function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

async function cookieHeader(): Promise<string> {
  const jar = await cookies();
  return jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

/**
 * Carrega o operador autenticado, redirecionando para /login se a sessão
 * estiver ausente ou inválida. Use no topo de páginas RSC protegidas.
 */
export async function exigirOperador(): Promise<OperadorRSC> {
  const res = await fetch(`${getApiUrl()}/v1/auth/me`, {
    headers: { Cookie: await cookieHeader() },
    cache: "no-store",
  });
  if (res.status === 401) {
    redirect("/login");
  }
  if (!res.ok) {
    throw new Error(`Falha ao verificar sessão (HTTP ${res.status}).`);
  }
  return (await res.json()) as OperadorRSC;
}

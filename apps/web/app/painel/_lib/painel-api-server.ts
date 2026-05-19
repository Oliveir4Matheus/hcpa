/**
 * Cliente server-side do painel.
 *
 * O proxy `/api/*` configurado no Next só serve a fetches do browser. No
 * server (RSC, route handlers), falamos diretamente com `API_URL` e
 * repassamos o cookie `hcpa_admin_sessao` lido via `next/headers`.
 */

import { cookies } from "next/headers";
import { PainelError, type CentroCustoListOut } from "./painel-api";

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

export async function getCentrosCustoServer(): Promise<CentroCustoListOut> {
  const res = await fetch(`${getApiUrl()}/v1/centros-custo`, {
    headers: { Cookie: await cookieHeader() },
    cache: "no-store",
  });
  if (res.status === 401) {
    throw new PainelError("nao_autenticado", "Sessão expirada ou ausente.");
  }
  if (!res.ok) {
    throw new PainelError("erro_desconhecido", `HTTP ${res.status}`);
  }
  return (await res.json()) as CentroCustoListOut;
}

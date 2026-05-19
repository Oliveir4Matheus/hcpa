/**
 * Cliente browser-side do painel.
 *
 * Usa o proxy `/api/*` configurado no Next (next.config.ts) — fetches do
 * browser saem da mesma origem do HTML, então o cookie `hcpa_admin_sessao`
 * (HttpOnly + SameSite=lax) chega à API sem CORS.
 *
 * Para fetches server-side (RSC), use o cliente `painel-api-server.ts`,
 * que repassa o cookie do request via `next/headers` e fala direto com
 * `API_URL`.
 */

export type CentroCustoOut = {
  id: string;
  codigo: string;
  nome: string;
  bloco_predio: string | null;
  total_colaboradores: number;
};

export type CentroCustoListOut = {
  itens: CentroCustoOut[];
  total: number;
};

export type AgregadoBucket = {
  tipo: "centro_custo" | "bloco_predio";
  valor: string;
};

export type AgregadoDominio = {
  dominio_id: string;
  dominio_nome: string;
  n_respostas: number;
  media_valor: number;
};

export type AgregadoSupressao = {
  motivo: "k_anonimato_insuficiente";
  minimo_requerido: number;
  n_atual: number;
};

export type AgregadoOut = {
  centro_custo_id: string;
  bucket: AgregadoBucket;
  n_questionarios: number;
  por_dominio: AgregadoDominio[];
  supressao: AgregadoSupressao | null;
};

export class PainelError extends Error {
  constructor(
    public readonly code: string,
    mensagem: string,
  ) {
    super(mensagem);
    this.name = "PainelError";
  }
}

async function lerErro(res: Response): Promise<PainelError> {
  if (res.status === 401) {
    return new PainelError("nao_autenticado", "Sessão expirada ou ausente.");
  }
  let code = "erro_desconhecido";
  let mensagem = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as {
      detail?: { code?: string; mensagem?: string };
    };
    if (body.detail?.code) code = body.detail.code;
    if (body.detail?.mensagem) mensagem = body.detail.mensagem;
  } catch {
    // mantém defaults
  }
  return new PainelError(code, mensagem);
}

export async function getCentrosCusto(): Promise<CentroCustoListOut> {
  const res = await fetch("/api/v1/centros-custo", {
    credentials: "same-origin",
  });
  if (!res.ok) throw await lerErro(res);
  return (await res.json()) as CentroCustoListOut;
}

export async function getAgregado(
  centroCustoId: string,
): Promise<AgregadoOut> {
  const qs = new URLSearchParams({ centro_custo_id: centroCustoId });
  const res = await fetch(`/api/v1/respostas/agregado?${qs}`, {
    credentials: "same-origin",
  });
  if (!res.ok) throw await lerErro(res);
  return (await res.json()) as AgregadoOut;
}

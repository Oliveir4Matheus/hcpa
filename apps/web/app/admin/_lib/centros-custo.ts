/**
 * Cliente browser-side do admin (import de centros de custo).
 *
 * Usa o proxy `/api/*` configurado no Next (next.config.ts) — fetches saem
 * da mesma origem do HTML, então o cookie `hcpa_admin_sessao` (HttpOnly +
 * SameSite=lax) chega à API sem CORS.
 *
 * A partir de Sprint 1 #2, os endpoints de import exigem operador
 * autenticado. Em 401 lançamos `CentrosCustoError` com code estável
 * `nao_autenticado` para que a UI possa redirecionar para /login.
 */

export type CentroCustoItem = {
  codigo: string;
  nome: string;
  bloco_predio: string | null;
  codigo_pai: string | null;
  total_colaboradores: number;
};

export type ParseError = { linha: number; mensagem: string };

export type ParseResult =
  | { ok: true; itens: CentroCustoItem[] }
  | { ok: false; erros: ParseError[] };

export type PreviewIssue = { codigo: string; erro: string };

export type PreviewResponse = {
  total: number;
  novos: string[];
  atualizados: string[];
  erros: PreviewIssue[];
  valido: boolean;
};

export type CommitResponse = {
  criados: number;
  atualizados: number;
};

export class CentrosCustoError extends Error {
  constructor(
    public readonly code: string,
    mensagem: string,
  ) {
    super(mensagem);
    this.name = "CentrosCustoError";
  }
}

const COLUNAS_OBRIGATORIAS = [
  "codigo",
  "nome",
  "bloco_predio",
  "codigo_pai",
  "total_colaboradores",
] as const;

type ColunaObrigatoria = (typeof COLUNAS_OBRIGATORIAS)[number];

function parseLinhaCsv(linha: string): string[] {
  const campos: string[] = [];
  let buffer = "";
  let dentroAspas = false;
  for (let i = 0; i < linha.length; i++) {
    const ch = linha[i];
    if (dentroAspas) {
      if (ch === '"' && linha[i + 1] === '"') {
        buffer += '"';
        i++;
      } else if (ch === '"') {
        dentroAspas = false;
      } else {
        buffer += ch;
      }
    } else if (ch === '"') {
      dentroAspas = true;
    } else if (ch === ",") {
      campos.push(buffer);
      buffer = "";
    } else {
      buffer += ch;
    }
  }
  campos.push(buffer);
  return campos;
}

export function parseCsvCentrosCusto(texto: string): ParseResult {
  const normalizado = texto.replace(/\r\n?/g, "\n").trim();
  if (!normalizado) {
    return { ok: false, erros: [{ linha: 0, mensagem: "Arquivo vazio." }] };
  }

  const linhas = normalizado.split("\n");
  const header = parseLinhaCsv(linhas[0]).map((c) => c.trim().toLowerCase());
  const faltando = COLUNAS_OBRIGATORIAS.filter((c) => !header.includes(c));
  if (faltando.length > 0) {
    return {
      ok: false,
      erros: [
        {
          linha: 1,
          mensagem: `Cabeçalho inválido. Colunas faltando: ${faltando.join(", ")}.`,
        },
      ],
    };
  }

  const indices = Object.fromEntries(
    COLUNAS_OBRIGATORIAS.map((c) => [c, header.indexOf(c)]),
  ) as Record<ColunaObrigatoria, number>;

  const itens: CentroCustoItem[] = [];
  const erros: ParseError[] = [];

  for (let i = 1; i < linhas.length; i++) {
    const numeroLinha = i + 1;
    const linha = linhas[i];
    if (!linha.trim()) continue;
    const campos = parseLinhaCsv(linha).map((c) => c.trim());

    const codigo = campos[indices.codigo] ?? "";
    const nome = campos[indices.nome] ?? "";
    const blocoPredio = campos[indices.bloco_predio] ?? "";
    const codigoPai = campos[indices.codigo_pai] ?? "";
    const totalRaw = campos[indices.total_colaboradores] ?? "";

    if (!codigo) {
      erros.push({ linha: numeroLinha, mensagem: "Coluna 'codigo' obrigatória." });
      continue;
    }
    if (!nome) {
      erros.push({ linha: numeroLinha, mensagem: "Coluna 'nome' obrigatória." });
      continue;
    }

    let total = 0;
    if (totalRaw) {
      const parsed = Number(totalRaw);
      if (!Number.isFinite(parsed) || parsed < 0 || !Number.isInteger(parsed)) {
        erros.push({
          linha: numeroLinha,
          mensagem: `'total_colaboradores' inválido: '${totalRaw}'. Use inteiro ≥ 0.`,
        });
        continue;
      }
      total = parsed;
    }

    itens.push({
      codigo,
      nome,
      bloco_predio: blocoPredio || null,
      codigo_pai: codigoPai || null,
      total_colaboradores: total,
    });
  }

  if (erros.length > 0) {
    return { ok: false, erros };
  }
  if (itens.length === 0) {
    return {
      ok: false,
      erros: [{ linha: 0, mensagem: "Nenhuma linha de dados encontrada." }],
    };
  }
  return { ok: true, itens };
}

async function lerErro(res: Response, fallbackMensagem: string): Promise<CentrosCustoError> {
  if (res.status === 401) {
    return new CentrosCustoError(
      "nao_autenticado",
      "Sessão expirada ou ausente.",
    );
  }
  let code = "erro_desconhecido";
  let mensagem = fallbackMensagem;
  try {
    const body = (await res.json()) as {
      detail?:
        | { code?: string; mensagem?: string; erros?: PreviewIssue[] }
        | string;
    };
    if (typeof body.detail === "object" && body.detail !== null) {
      if (body.detail.code) code = body.detail.code;
      if (body.detail.mensagem) mensagem = body.detail.mensagem;
      if (body.detail.erros && body.detail.erros.length > 0) {
        code = "payload_invalido";
        mensagem = body.detail.erros
          .map((e) => `${e.codigo}: ${e.erro}`)
          .join("; ");
      }
    }
  } catch {
    // resposta não-JSON, mantém defaults
  }
  return new CentrosCustoError(code, mensagem);
}

export async function postPreview(
  itens: CentroCustoItem[],
): Promise<PreviewResponse> {
  const res = await fetch("/api/v1/centros-custo/import/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ itens }),
  });
  if (!res.ok) throw await lerErro(res, `Preview falhou (HTTP ${res.status}).`);
  return (await res.json()) as PreviewResponse;
}

export async function postCommit(
  itens: CentroCustoItem[],
): Promise<CommitResponse> {
  const res = await fetch("/api/v1/centros-custo/import/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ itens }),
  });
  if (!res.ok) throw await lerErro(res, `Commit falhou (HTTP ${res.status}).`);
  return (await res.json()) as CommitResponse;
}

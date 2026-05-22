"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  CentrosCustoError,
  parseCsvCentrosCusto,
  postCommit,
  postPreview,
  type CentroCustoItem,
  type CommitResponse,
  type ParseError,
  type PreviewResponse,
} from "../_lib/centros-custo";

type Estado =
  | { tipo: "idle" }
  | { tipo: "parse-erro"; nomeArquivo: string; erros: ParseError[] }
  | { tipo: "parsed"; nomeArquivo: string; itens: CentroCustoItem[] }
  | {
      tipo: "preview-loading";
      nomeArquivo: string;
      itens: CentroCustoItem[];
    }
  | {
      tipo: "preview-ok";
      nomeArquivo: string;
      itens: CentroCustoItem[];
      preview: PreviewResponse;
    }
  | { tipo: "preview-erro"; nomeArquivo: string; mensagem: string }
  | {
      tipo: "commit-loading";
      nomeArquivo: string;
      itens: CentroCustoItem[];
    }
  | { tipo: "commit-ok"; nomeArquivo: string; resultado: CommitResponse }
  | { tipo: "commit-erro"; nomeArquivo: string; mensagem: string };

export function UploadCentrosCusto() {
  const router = useRouter();
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });

  function tratarErroOuRedirecionar(err: unknown): string {
    if (err instanceof CentrosCustoError && err.code === "nao_autenticado") {
      router.push("/login");
      return "Sessão expirada — redirecionando para login.";
    }
    return err instanceof Error ? err.message : String(err);
  }

  async function aoSelecionarArquivo(arquivo: File) {
    const texto = await arquivo.text();
    const resultado = parseCsvCentrosCusto(texto);
    if (!resultado.ok) {
      setEstado({
        tipo: "parse-erro",
        nomeArquivo: arquivo.name,
        erros: resultado.erros,
      });
      return;
    }
    setEstado({
      tipo: "parsed",
      nomeArquivo: arquivo.name,
      itens: resultado.itens,
    });
  }

  async function executarPreview(itens: CentroCustoItem[], nomeArquivo: string) {
    setEstado({ tipo: "preview-loading", nomeArquivo, itens });
    try {
      const preview = await postPreview(itens);
      setEstado({ tipo: "preview-ok", nomeArquivo, itens, preview });
    } catch (err) {
      setEstado({
        tipo: "preview-erro",
        nomeArquivo,
        mensagem: tratarErroOuRedirecionar(err),
      });
    }
  }

  async function executarCommit(itens: CentroCustoItem[], nomeArquivo: string) {
    setEstado({ tipo: "commit-loading", nomeArquivo, itens });
    try {
      const resultado = await postCommit(itens);
      setEstado({ tipo: "commit-ok", nomeArquivo, resultado });
    } catch (err) {
      setEstado({
        tipo: "commit-erro",
        nomeArquivo,
        mensagem: tratarErroOuRedirecionar(err),
      });
    }
  }

  function reiniciar() {
    setEstado({ tipo: "idle" });
  }

  return (
    <section className="space-y-6">
      <SeletorArquivo
        desabilitado={
          estado.tipo === "preview-loading" || estado.tipo === "commit-loading"
        }
        nomeAtual={"nomeArquivo" in estado ? estado.nomeArquivo : null}
        onArquivo={aoSelecionarArquivo}
      />

      {estado.tipo === "parse-erro" && (
        <PainelErrosParse erros={estado.erros} onReiniciar={reiniciar} />
      )}

      {(estado.tipo === "parsed" ||
        estado.tipo === "preview-loading" ||
        estado.tipo === "preview-erro") && (
        <PainelParseado
          quantidade={
            "itens" in estado
              ? estado.itens.length
              : 0
          }
          estado={estado.tipo}
          mensagemErro={
            estado.tipo === "preview-erro" ? estado.mensagem : undefined
          }
          onValidar={() =>
            estado.tipo !== "preview-erro" &&
            "itens" in estado &&
            executarPreview(estado.itens, estado.nomeArquivo)
          }
        />
      )}

      {estado.tipo === "preview-ok" && (
        <PainelPreview
          preview={estado.preview}
          carregandoCommit={false}
          onConfirmar={() =>
            executarCommit(estado.itens, estado.nomeArquivo)
          }
          onCancelar={reiniciar}
        />
      )}

      {estado.tipo === "commit-loading" && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Persistindo no banco…
        </p>
      )}

      {estado.tipo === "commit-ok" && (
        <PainelCommitOk
          resultado={estado.resultado}
          onReiniciar={reiniciar}
        />
      )}

      {estado.tipo === "commit-erro" && (
        <PainelCommitErro
          mensagem={estado.mensagem}
          onReiniciar={reiniciar}
        />
      )}
    </section>
  );
}

function SeletorArquivo({
  desabilitado,
  nomeAtual,
  onArquivo,
}: {
  desabilitado: boolean;
  nomeAtual: string | null;
  onArquivo: (arquivo: File) => void;
}) {
  return (
    <div className="rounded-lg border border-dashed border-neutral-300 p-6 dark:border-neutral-700">
      <label className="block">
        <span className="text-sm font-medium">Arquivo CSV</span>
        <input
          type="file"
          accept=".csv,text/csv"
          disabled={desabilitado}
          onChange={(e) => {
            const arquivo = e.target.files?.[0];
            if (arquivo) onArquivo(arquivo);
          }}
          className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-neutral-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-neutral-700 dark:file:bg-neutral-100 dark:file:text-neutral-900"
        />
      </label>
      {nomeAtual && (
        <p className="mt-3 text-xs text-neutral-500">
          Arquivo selecionado: <span className="font-mono">{nomeAtual}</span>
        </p>
      )}
    </div>
  );
}

function PainelErrosParse({
  erros,
  onReiniciar,
}: {
  erros: ParseError[];
  onReiniciar: () => void;
}) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950">
      <h3 className="font-semibold text-red-900 dark:text-red-200">
        Falha ao ler o CSV
      </h3>
      <ul className="mt-2 list-inside list-disc space-y-1 text-red-800 dark:text-red-200">
        {erros.map((e, i) => (
          <li key={i}>
            {e.linha > 0 && <span className="font-mono">linha {e.linha}: </span>}
            {e.mensagem}
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onReiniciar}
        className="mt-3 text-xs underline"
      >
        Selecionar outro arquivo
      </button>
    </div>
  );
}

function PainelParseado({
  quantidade,
  estado,
  mensagemErro,
  onValidar,
}: {
  quantidade: number;
  estado: "parsed" | "preview-loading" | "preview-erro";
  mensagemErro?: string;
  onValidar: () => void;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <p className="text-sm">
        <span className="font-semibold">{quantidade}</span> linha(s) lida(s) do
        CSV. Clique em validar para conferir a hierarquia com o backend.
      </p>
      <button
        type="button"
        onClick={onValidar}
        disabled={estado === "preview-loading"}
        className="mt-3 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
      >
        {estado === "preview-loading" ? "Validando…" : "Validar (preview)"}
      </button>
      {estado === "preview-erro" && mensagemErro && (
        <p className="mt-3 text-sm text-red-700 dark:text-red-300">
          {mensagemErro}
        </p>
      )}
    </div>
  );
}

function PainelPreview({
  preview,
  carregandoCommit,
  onConfirmar,
  onCancelar,
}: {
  preview: PreviewResponse;
  carregandoCommit: boolean;
  onConfirmar: () => void;
  onCancelar: () => void;
}) {
  return (
    <div
      className={`rounded-lg border p-4 text-sm ${
        preview.valido
          ? "border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950"
          : "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950"
      }`}
    >
      <h3 className="font-semibold">
        Pré-visualização do import — {preview.valido ? "válida" : "inválida"}
      </h3>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <Metrica titulo="Total" valor={preview.total} />
        <Metrica titulo="Novos" valor={preview.novos.length} />
        <Metrica titulo="Atualizados" valor={preview.atualizados.length} />
      </dl>

      {preview.novos.length > 0 && (
        <ListaCodigos titulo="Novos" codigos={preview.novos} />
      )}
      {preview.atualizados.length > 0 && (
        <ListaCodigos titulo="Atualizados" codigos={preview.atualizados} />
      )}
      {preview.erros.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-900 dark:text-amber-200">
            Problemas detectados
          </p>
          <ul className="mt-1 list-inside list-disc space-y-1">
            {preview.erros.map((e, i) => (
              <li key={i}>
                <span className="font-mono">{e.codigo}</span> — {e.erro}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={onConfirmar}
          disabled={!preview.valido || carregandoCommit}
          className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {carregandoCommit ? "Persistindo…" : "Confirmar import (commit)"}
        </button>
        <button
          type="button"
          onClick={onCancelar}
          className="rounded-md border border-neutral-300 px-4 py-2 text-sm dark:border-neutral-700"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}

function PainelCommitOk({
  resultado,
  onReiniciar,
}: {
  resultado: CommitResponse;
  onReiniciar: () => void;
}) {
  return (
    <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm dark:border-emerald-900 dark:bg-emerald-950">
      <h3 className="font-semibold text-emerald-900 dark:text-emerald-200">
        Import concluído
      </h3>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <Metrica titulo="Criados" valor={resultado.criados} />
        <Metrica titulo="Atualizados" valor={resultado.atualizados} />
      </dl>
      <button
        type="button"
        onClick={onReiniciar}
        className="mt-4 text-xs underline"
      >
        Carregar outro arquivo
      </button>
    </div>
  );
}

function PainelCommitErro({
  mensagem,
  onReiniciar,
}: {
  mensagem: string;
  onReiniciar: () => void;
}) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950">
      <h3 className="font-semibold text-red-900 dark:text-red-200">
        Falha no commit
      </h3>
      <p className="mt-2 break-all text-red-800 dark:text-red-200">{mensagem}</p>
      <button
        type="button"
        onClick={onReiniciar}
        className="mt-3 text-xs underline"
      >
        Recomeçar
      </button>
    </div>
  );
}

function Metrica({ titulo, valor }: { titulo: string; valor: number }) {
  return (
    <div className="rounded-md bg-white/60 px-3 py-2 dark:bg-black/30">
      <dt className="text-[10px] uppercase tracking-wide text-neutral-500">
        {titulo}
      </dt>
      <dd className="text-base font-semibold">{valor}</dd>
    </div>
  );
}

function ListaCodigos({
  titulo,
  codigos,
}: {
  titulo: string;
  codigos: string[];
}) {
  return (
    <div className="mt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-600 dark:text-neutral-400">
        {titulo} ({codigos.length})
      </p>
      <p className="mt-1 font-mono text-xs break-all">{codigos.join(", ")}</p>
    </div>
  );
}

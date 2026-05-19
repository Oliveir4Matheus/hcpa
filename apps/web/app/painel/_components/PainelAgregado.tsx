"use client";

import { useEffect, useState } from "react";
import {
  PainelError,
  getAgregado,
  type AgregadoOut,
  type CentroCustoOut,
} from "../_lib/painel-api";

type Estado =
  | { tipo: "ocioso" }
  | { tipo: "carregando" }
  | { tipo: "carregado"; agregado: AgregadoOut }
  | { tipo: "erro"; code: string; mensagem: string };

export function PainelAgregado({ centros }: { centros: CentroCustoOut[] }) {
  const [ccId, setCcId] = useState<string>("");
  const [estado, setEstado] = useState<Estado>({ tipo: "ocioso" });

  useEffect(() => {
    if (!ccId) {
      setEstado({ tipo: "ocioso" });
      return;
    }
    let cancelado = false;
    setEstado({ tipo: "carregando" });
    getAgregado(ccId)
      .then((agregado) => {
        if (!cancelado) setEstado({ tipo: "carregado", agregado });
      })
      .catch((err: unknown) => {
        if (cancelado) return;
        const code =
          err instanceof PainelError ? err.code : "erro_desconhecido";
        const mensagem =
          err instanceof Error ? err.message : String(err);
        setEstado({ tipo: "erro", code, mensagem });
      });
    return () => {
      cancelado = true;
    };
  }, [ccId]);

  return (
    <div className="space-y-6">
      <label className="block text-sm">
        <span className="block font-medium">Centro de custo</span>
        <select
          aria-label="Centro de custo"
          value={ccId}
          onChange={(e) => setCcId(e.target.value)}
          className="mt-1 block w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
        >
          <option value="">— escolha um CC —</option>
          {centros.map((cc) => (
            <option key={cc.id} value={cc.id}>
              {cc.codigo} · {cc.nome} ({cc.total_colaboradores})
            </option>
          ))}
        </select>
      </label>

      {estado.tipo === "carregando" && (
        <p role="status" className="text-sm text-neutral-500">
          Carregando agregado…
        </p>
      )}

      {estado.tipo === "erro" && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <span className="font-mono text-xs">{estado.code}</span> —{" "}
          {estado.mensagem}
        </p>
      )}

      {estado.tipo === "carregado" && (
        <ResultadoAgregado agregado={estado.agregado} centros={centros} />
      )}
    </div>
  );
}

function rotuloBucket(
  agregado: AgregadoOut,
  centros: CentroCustoOut[],
): string {
  if (agregado.bucket.tipo === "bloco_predio") return agregado.bucket.valor;
  const cc = centros.find((c) => c.id === agregado.centro_custo_id);
  return cc ? `${cc.codigo} · ${cc.nome}` : agregado.bucket.valor;
}

function ResultadoAgregado({
  agregado,
  centros,
}: {
  agregado: AgregadoOut;
  centros: CentroCustoOut[];
}) {
  const bucketLabel =
    agregado.bucket.tipo === "centro_custo"
      ? "Agregação por centro de custo"
      : "Agregação por bloco/prédio (CC pequeno)";

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          {bucketLabel}
        </p>
        <p className="text-lg font-semibold">{rotuloBucket(agregado, centros)}</p>
        <p className="text-xs text-neutral-500">
          {agregado.n_questionarios} questionário(s) concluído(s)
        </p>
      </header>

      {agregado.supressao ? (
        <p
          role="status"
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          Agregado suprimido por k-anonimato: mínimo de{" "}
          <strong>{agregado.supressao.minimo_requerido}</strong> questionários,
          atual <strong>{agregado.supressao.n_atual}</strong>.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="py-2">Domínio COPSOQ-II</th>
              <th className="py-2 text-right">N respostas</th>
              <th className="py-2 text-right">Média (0–4)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {agregado.por_dominio.map((d) => (
              <tr key={d.dominio_id}>
                <td className="py-2">{d.dominio_nome}</td>
                <td className="py-2 text-right tabular-nums">
                  {d.n_respostas}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {d.media_valor.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

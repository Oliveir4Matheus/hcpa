import Link from "next/link";
import { exigirOperador } from "../_lib/auth-server";
import { UploadCentrosCusto } from "./_components/UploadCentrosCusto";

export const metadata = {
  title: "Admin · Plataforma HCPA",
};

export default async function AdminPage() {
  await exigirOperador();

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <nav className="text-xs text-neutral-500">
        <Link href="/" className="hover:underline">
          ← voltar
        </Link>
      </nav>

      <header className="mt-4 space-y-2">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          Admin HMind · Sprint 1
        </p>
        <h1 className="text-2xl font-semibold">
          Import de centros de custo
        </h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Envie um arquivo CSV com a estrutura organizacional. O sistema faz uma
          pré-validação local, valida a hierarquia no backend (preview) e só
          persiste após confirmação (commit). Idempotente — re-imports
          atualizam os registros existentes.
        </p>
      </header>

      <section className="mt-6 rounded-md bg-neutral-50 p-4 text-xs text-neutral-700 dark:bg-neutral-900/50 dark:text-neutral-300">
        <p className="font-semibold uppercase tracking-wide">Formato esperado</p>
        <p className="mt-2">Cabeçalho obrigatório:</p>
        <pre className="mt-1 overflow-x-auto rounded bg-white p-2 font-mono text-[11px] dark:bg-black/40">
{`codigo,nome,bloco_predio,codigo_pai,total_colaboradores`}
        </pre>
        <ul className="mt-2 list-inside list-disc space-y-1">
          <li><span className="font-mono">codigo</span> e <span className="font-mono">nome</span> são obrigatórios.</li>
          <li><span className="font-mono">bloco_predio</span> e <span className="font-mono">codigo_pai</span> podem ficar vazios.</li>
          <li><span className="font-mono">total_colaboradores</span> aceita inteiro ≥ 0 (vazio = 0).</li>
          <li>A hierarquia é referenciada pelo <span className="font-mono">codigo</span> (não pelo UUID).</li>
        </ul>
      </section>

      <div className="mt-8">
        <UploadCentrosCusto />
      </div>
    </main>
  );
}

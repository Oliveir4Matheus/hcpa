import Link from "next/link";
import { redirect } from "next/navigation";
import { PainelAgregado } from "./_components/PainelAgregado";
import { PainelError } from "./_lib/painel-api";
import { getCentrosCustoServer } from "./_lib/painel-api-server";

export const metadata = {
  title: "Painel · Plataforma HCPA",
};

export default async function PainelPage() {
  let centros;
  try {
    const lista = await getCentrosCustoServer();
    centros = lista.itens;
  } catch (err) {
    if (err instanceof PainelError && err.code === "nao_autenticado") {
      redirect("/login");
    }
    throw err;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <nav className="text-xs text-neutral-500">
        <Link href="/" className="hover:underline">
          ← voltar
        </Link>
      </nav>

      <header className="mt-4 space-y-2">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          Painel HMind · Sprint 1
        </p>
        <h1 className="text-2xl font-semibold">Agregado COPSOQ-II por CC</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Escolha um centro de custo para ver a média por domínio. CCs pequenos
          caem para a granularidade de bloco/prédio; agregados com menos de 5
          questionários concluídos são suprimidos para preservar k-anonimato.
        </p>
      </header>

      <div className="mt-8">
        {centros.length === 0 ? (
          <p className="text-sm text-neutral-500">
            Nenhum centro de custo importado ainda. Use o{" "}
            <Link
              href={{ pathname: "/admin" }}
              className="underline hover:no-underline"
            >
              admin
            </Link>{" "}
            para importar a estrutura.
          </p>
        ) : (
          <PainelAgregado centros={centros} />
        )}
      </div>
    </main>
  );
}

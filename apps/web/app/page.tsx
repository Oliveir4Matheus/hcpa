import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          DartenMind · Sprint 0
        </p>
        <h1 className="text-3xl font-semibold sm:text-4xl">
          Plataforma HCPA
        </h1>
        <p className="text-neutral-600 dark:text-neutral-400">
          Avaliação de fatores de risco psicossocial (NR-1 / COPSOQ II-Br).
        </p>
      </header>

      <section className="grid gap-4 sm:grid-cols-3">
        <AreaCard
          href="/respondente"
          title="Respondente"
          description="Acesso por senha individual"
        />
        <AreaCard
          href="/painel"
          title="Painel HCPA"
          description="Andamento e IMRs em tempo real"
        />
        <AreaCard
          href="/admin"
          title="Admin HMind"
          description="Operação e configuração"
        />
      </section>

      <footer className="text-xs text-neutral-500">
        Scaffold inicial — sem lógica de negócio. Próximo passo: Sprint 1
        (modelagem PG + import CSV centros de custo).
      </footer>
    </main>
  );
}

function AreaCard({
  href,
  title,
  description,
}: {
  href: "/respondente" | "/painel" | "/admin";
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-neutral-200 p-4 transition hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600"
    >
      <h2 className="text-base font-medium">{title}</h2>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {description}
      </p>
    </Link>
  );
}

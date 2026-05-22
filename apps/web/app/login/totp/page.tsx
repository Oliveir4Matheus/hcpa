import Link from "next/link";
import { TotpForm } from "./_components/TotpForm";

export const metadata = {
  title: "Verificação TOTP · Plataforma HCPA",
};

type Props = {
  searchParams: Promise<{ email?: string }>;
};

export default async function LoginTotpPage({ searchParams }: Props) {
  const { email } = await searchParams;

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <nav className="text-xs text-neutral-500">
        <Link href="/login" className="hover:underline">
          ← voltar ao login
        </Link>
      </nav>

      <header className="mt-4 space-y-2">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          Admin HMind · Painel
        </p>
        <h1 className="text-2xl font-semibold">Verificação em duas etapas</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          {email ? (
            <>
              Informe o código de 6 dígitos do app autenticador do operador{" "}
              <span className="font-mono">{email}</span>.
            </>
          ) : (
            <>Informe o código de 6 dígitos do app autenticador.</>
          )}
        </p>
      </header>

      <section className="mt-8">
        <TotpForm />
      </section>
    </main>
  );
}

import Link from "next/link";
import { LoginForm } from "./_components/LoginForm";

export const metadata = {
  title: "Login · Plataforma HCPA",
};

export default function LoginPage() {
  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <nav className="text-xs text-neutral-500">
        <Link href="/" className="hover:underline">
          ← voltar
        </Link>
      </nav>

      <header className="mt-4 space-y-2">
        <p className="text-xs uppercase tracking-widest text-neutral-500">
          Admin HMind · Painel
        </p>
        <h1 className="text-2xl font-semibold">Entrar no painel</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Acesso restrito a operadores autenticados. O painel agrega respostas
          respeitando granularidade e k-anonimato em consulta.
        </p>
      </header>

      <section className="mt-8">
        <LoginForm />
      </section>
    </main>
  );
}

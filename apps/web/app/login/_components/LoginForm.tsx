"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoginError, postLogin } from "../_lib/auth-api";

type Estado =
  | { tipo: "idle" }
  | { tipo: "enviando" }
  | { tipo: "totp_pendente"; email: string }
  | { tipo: "erro"; mensagem: string };

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });

  async function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setEstado({ tipo: "enviando" });
    try {
      const r = await postLogin(email, senha);
      if (r.totp_required) {
        setEstado({ tipo: "totp_pendente", email: r.email });
        return;
      }
      router.push("/painel");
    } catch (err) {
      const mensagem =
        err instanceof LoginError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err);
      setEstado({ tipo: "erro", mensagem });
    }
  }

  const enviando = estado.tipo === "enviando";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="email" className="block text-sm font-medium">
          E-mail
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={enviando}
          className="mt-1 block w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:focus:border-neutral-100"
        />
      </div>
      <div>
        <label htmlFor="senha" className="block text-sm font-medium">
          Senha
        </label>
        <input
          id="senha"
          type="password"
          autoComplete="current-password"
          required
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          disabled={enviando}
          className="mt-1 block w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:focus:border-neutral-100"
        />
      </div>
      <button
        type="submit"
        disabled={enviando}
        className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
      >
        {enviando ? "Entrando…" : "Entrar"}
      </button>

      {estado.tipo === "totp_pendente" && (
        <p
          role="status"
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          Operador <span className="font-mono">{estado.email}</span> exige TOTP.
          A verificação TOTP pelo painel ainda não está implementada —
          desabilite o TOTP do seu operador com o admin para entrar por aqui.
        </p>
      )}
      {estado.tipo === "erro" && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          {estado.mensagem}
        </p>
      )}
    </form>
  );
}

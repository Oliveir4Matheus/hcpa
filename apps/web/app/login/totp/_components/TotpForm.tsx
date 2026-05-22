"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoginError, postTotpVerify } from "../../_lib/auth-api";

type Estado =
  | { tipo: "idle" }
  | { tipo: "enviando" }
  | { tipo: "erro"; code: string; mensagem: string };

const MENSAGEM_POR_CODE: Record<string, string> = {
  totp_invalido: "Código inválido ou expirado. Tente novamente.",
  sessao_ausente:
    "A sessão de login expirou. Faça login novamente para continuar.",
  sessao_expirada:
    "A sessão de login expirou. Faça login novamente para continuar.",
  sessao_estado_invalido:
    "Sessão em estado inválido. Faça login novamente.",
};

export function TotpForm() {
  const router = useRouter();
  const [codigo, setCodigo] = useState("");
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });

  async function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setEstado({ tipo: "enviando" });
    try {
      await postTotpVerify(codigo);
      router.push("/painel");
    } catch (err) {
      if (err instanceof LoginError) {
        setEstado({
          tipo: "erro",
          code: err.code,
          mensagem: MENSAGEM_POR_CODE[err.code] ?? err.message,
        });
        return;
      }
      const mensagem = err instanceof Error ? err.message : String(err);
      setEstado({ tipo: "erro", code: "erro_desconhecido", mensagem });
    }
  }

  const enviando = estado.tipo === "enviando";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="codigo" className="block text-sm font-medium">
          Código TOTP
        </label>
        <input
          id="codigo"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6,8}"
          required
          minLength={6}
          maxLength={8}
          value={codigo}
          onChange={(e) => setCodigo(e.target.value.replace(/\s/g, ""))}
          disabled={enviando}
          aria-describedby="codigo-hint"
          className="mt-1 block w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-lg tracking-widest focus:border-neutral-900 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:focus:border-neutral-100"
        />
        <p id="codigo-hint" className="mt-1 text-xs text-neutral-500">
          6 dígitos do app autenticador (Authy, Google Authenticator, 1Password etc).
        </p>
      </div>
      <button
        type="submit"
        disabled={enviando}
        className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
      >
        {enviando ? "Verificando…" : "Verificar"}
      </button>

      {estado.tipo === "erro" && (
        <p
          role="alert"
          data-code={estado.code}
          className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          {estado.mensagem}
        </p>
      )}
    </form>
  );
}

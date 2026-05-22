"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoginError, postTotpVerify } from "../_lib/auth-api";

type Estado =
  | { tipo: "idle" }
  | { tipo: "enviando" }
  | { tipo: "erro"; mensagem: string };

/**
 * Form de verificação TOTP exibido após o login com senha quando o operador
 * tem TOTP habilitado. A API já setou o cookie de sessão `pendente_totp`;
 * aqui só enviamos o código e, em caso de sucesso, navegamos para o painel.
 */
export function TotpForm({ email, onCancelar }: { email: string; onCancelar: () => void }) {
  const router = useRouter();
  const [codigo, setCodigo] = useState("");
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });

  async function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setEstado({ tipo: "enviando" });
    try {
      await postTotpVerify(codigo.trim());
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
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Verificação TOTP">
      <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-700 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300">
        Senha aceita para <span className="font-mono">{email}</span>. Digite o código
        de 6 dígitos do seu app autenticador para concluir o login.
      </div>

      <div>
        <label htmlFor="codigo-totp" className="block text-sm font-medium">
          Código TOTP
        </label>
        <input
          id="codigo-totp"
          name="codigo"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6,8}"
          minLength={6}
          maxLength={8}
          required
          autoFocus
          value={codigo}
          onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))}
          disabled={enviando}
          className="mt-1 block w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-base tracking-widest focus:border-neutral-900 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:focus:border-neutral-100"
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={enviando || codigo.length < 6}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {enviando ? "Verificando…" : "Verificar"}
        </button>
        <button
          type="button"
          onClick={onCancelar}
          disabled={enviando}
          className="rounded-md border border-neutral-300 px-4 py-2 text-sm dark:border-neutral-700"
        >
          Voltar
        </button>
      </div>

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

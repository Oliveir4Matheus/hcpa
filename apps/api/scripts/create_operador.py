"""CLI de bootstrap de operador do painel admin.

Uso (dentro do container API):
    docker compose exec api python -m scripts.create_operador \\
        --email admin@hcpa.example.com --senha 'troca-isso' --nome Admin

Senha pode vir via --senha (visível em ps) ou stdin (--stdin-senha).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.database import SessionLocal
from app.services.auth_service import AuthError, criar_operador


async def _run(email: str, senha: str, nome: str | None, sobrenome: str | None) -> int:
    async with SessionLocal() as session:
        try:
            op = await criar_operador(
                session, email=email, senha=senha, nome=nome, sobrenome=sobrenome
            )
        except AuthError as exc:
            print(f"erro: {exc.code} — {exc.mensagem}", file=sys.stderr)
            return 2
        print(f"operador criado: id={op.id} email={op.email}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria um operador do painel admin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nome")
    parser.add_argument("--sobrenome")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--senha", help="senha em texto (visível em ps)")
    g.add_argument(
        "--stdin-senha",
        action="store_true",
        help="lê a senha de stdin (uma linha, sem quebra)",
    )
    args = parser.parse_args(argv)

    senha = args.senha if args.senha is not None else sys.stdin.readline().rstrip("\n")
    if not senha:
        print("erro: senha vazia", file=sys.stderr)
        return 2

    return asyncio.run(_run(args.email, senha, args.nome, args.sobrenome))


if __name__ == "__main__":
    raise SystemExit(main())

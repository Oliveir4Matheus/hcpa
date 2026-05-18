#!/usr/bin/env bash
# Smoke test E2E do fluxo de autenticação do operador contra o stack rodando.
# Cobre: criação via CLI, login sem TOTP, /me autorizado, /me não autorizado,
# senha errada, logout, e re-acesso bloqueado após logout.
# Roda a partir da raiz de `plataforma/`. Requer curl + jq + docker compose.

set -euo pipefail

API="${API_BASE:-http://localhost:8000}"
PG_USER="${POSTGRES_USER:-plataforma}"
PG_DB="${POSTGRES_DB:-plataforma}"
EMAIL="smoke-auth@example.com"
SENHA="senha-smoke-12345"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; FALHAS=$((FALHAS+1)); }

FALHAS=0
CJ=$(mktemp)
trap 'rm -f "$CJ"' EXIT

bold "== Preparação =="
docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -c \
  "DELETE FROM sessao_admin WHERE operador_id IN (SELECT id FROM operadores WHERE email = '$EMAIL'); \
   DELETE FROM operadores WHERE email = '$EMAIL';" >/dev/null
ok "operador de smoke removido"

bold "== 1. Criar operador via CLI =="
CRIA=$(docker compose exec -T api python -m scripts.create_operador \
  --email "$EMAIL" --senha "$SENHA" --nome Smoke --sobrenome Auth 2>&1 | tail -1)
echo "$CRIA" | grep -q '^operador criado' \
  && ok "operador criado: $CRIA" || fail "criar_operador falhou: $CRIA"

bold "== 2. Login com credenciais corretas =="
LOGIN_BODY=$(mktemp)
HTTP=$(curl -sS -o "$LOGIN_BODY" -c "$CJ" -w '%{http_code}' -X POST "$API/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"senha\":\"$SENHA\"}")
[[ "$HTTP" == "200" ]] && ok "login HTTP 200" || fail "login HTTP $HTTP — $(cat "$LOGIN_BODY")"
jq -e '.totp_required == false and .operador.email == "'"$EMAIL"'"' "$LOGIN_BODY" >/dev/null \
  && ok "resposta indica sessão ativa (totp_required=false)" || fail "resposta inesperada: $(cat "$LOGIN_BODY")"
grep -q hcpa_admin_sessao "$CJ" \
  && ok "cookie hcpa_admin_sessao foi setado" || fail "cookie ausente"

bold "== 3. /me com cookie =="
ME=$(curl -sS -b "$CJ" "$API/v1/auth/me")
echo "$ME" | jq -e '.email == "'"$EMAIL"'" and .totp_enabled == false' >/dev/null \
  && ok "/me devolveu o operador correto" || fail "/me errado: $ME"

bold "== 4. /me sem cookie devolve 401/sessao_ausente =="
HTTP=$(curl -sS -o /dev/null -w '%{http_code}' "$API/v1/auth/me")
[[ "$HTTP" == "401" ]] && ok "/me sem cookie HTTP 401" || fail "esperava 401, veio $HTTP"

bold "== 5. Login com senha errada devolve 401/credenciais_invalidas =="
BAD=$(curl -sS -X POST "$API/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"senha\":\"errada\"}")
echo "$BAD" | jq -e '.detail.code == "credenciais_invalidas"' >/dev/null \
  && ok "código estável credenciais_invalidas" || fail "código errado: $BAD"

bold "== 6. Logout encerra a sessão =="
OUT=$(curl -sS -b "$CJ" -X POST "$API/v1/auth/logout")
echo "$OUT" | jq -e '.detalhe' >/dev/null && ok "logout aceito" || fail "logout falhou: $OUT"

bold "== 7. /me após logout devolve 401 =="
HTTP=$(curl -sS -o /dev/null -w '%{http_code}' -b "$CJ" "$API/v1/auth/me")
[[ "$HTTP" == "401" ]] && ok "/me pós-logout HTTP 401" || fail "esperava 401, veio $HTTP"

bold "== 8. Trilha de auditoria registrou os eventos =="
COUNT=$(docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tA -c \
  "SELECT COUNT(*) FROM auditoria WHERE usuario = '$EMAIL' \
   AND acao IN ('operador_criado','login_sucesso','login_falhou','logout');")
[[ "$COUNT" -ge "4" ]] \
  && ok "$COUNT eventos de auditoria registrados (≥4 esperados)" \
  || fail "auditoria incompleta: $COUNT eventos"

bold "== Limpeza =="
docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -c \
  "DELETE FROM sessao_admin WHERE operador_id IN (SELECT id FROM operadores WHERE email = '$EMAIL'); \
   DELETE FROM operadores WHERE email = '$EMAIL'; \
   DELETE FROM auditoria WHERE usuario = '$EMAIL';" >/dev/null
ok "dados de smoke removidos"

bold "== Resumo =="
if [[ $FALHAS -eq 0 ]]; then
  printf '\033[1;32mTodos os checks passaram.\033[0m\n'
  exit 0
else
  printf '\033[1;31m%d check(s) falharam.\033[0m\n' "$FALHAS"
  exit 1
fi

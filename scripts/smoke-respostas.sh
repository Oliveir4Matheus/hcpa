#!/usr/bin/env bash
# Smoke E2E do fluxo de submissão de respostas + agregação para o painel.
# Cobre: submissão pública via token_anonimo (CC grande e bloco_predio),
# idempotência (re-submissão recusada), agregação autenticada com bucket
# correto (centro_custo vs bloco_predio), supressão k-anonimato.
# Roda a partir da raiz de `plataforma/`. Requer curl + jq + docker compose.

set -euo pipefail

API="${API_BASE:-http://localhost:8000}"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; FALHAS=$((FALHAS+1)); }

FALHAS=0
CJ=$(mktemp)
trap 'rm -f "$CJ"; docker compose exec -T api python -m scripts.seed_respostas_smoke --cleanup >/dev/null 2>&1 || true' EXIT

bold "== Preparação =="
# SQLAlchemy echo polui stdout em dev; extrair só a linha JSON.
SEED=$(docker compose exec -T api python -m scripts.seed_respostas_smoke 2>/dev/null | grep -E '^\{' | tail -1)
[[ -n "$SEED" ]] && ok "seed concluído" || { fail "seed retornou vazio"; exit 1; }

EMAIL=$(echo "$SEED" | jq -r '.operador.email')
SENHA=$(echo "$SEED" | jq -r '.operador.senha')
ITEM1=$(echo "$SEED" | jq -r '.itens[0]')
ITEM2=$(echo "$SEED" | jq -r '.itens[1]')
CC_G_ID=$(echo "$SEED"  | jq -r '.ccs["SMOKE-G"].id')
CC_P1_ID=$(echo "$SEED" | jq -r '.ccs["SMOKE-P1"].id')
CC_S_ID=$(echo "$SEED"  | jq -r '.ccs["SMOKE-S"].id')

bold "== 1. Login do operador =="
HTTP=$(curl -sS -c "$CJ" -o /dev/null -w '%{http_code}' -X POST "$API/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"senha\":\"$SENHA\"}")
[[ "$HTTP" == "200" ]] && ok "login HTTP 200" || fail "login HTTP $HTTP"

bold "== 2. Submissão pública nos questionários do CC grande (SMOKE-G) =="
N_OK=0
for tok in $(echo "$SEED" | jq -r '.ccs["SMOKE-G"].tokens[]'); do
  HTTP=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API/v1/questionarios/$tok/respostas" \
    -H 'Content-Type: application/json' \
    -d "{\"respostas\":[{\"item_id\":\"$ITEM1\",\"valor\":3},{\"item_id\":\"$ITEM2\",\"valor\":4}]}")
  [[ "$HTTP" == "201" ]] && N_OK=$((N_OK+1))
done
[[ "$N_OK" == "5" ]] && ok "5/5 submissões 201" || fail "$N_OK/5 submissões aceitas"

bold "== 3. Re-submissão no mesmo token devolve 409/questionario_ja_concluido =="
TOK=$(echo "$SEED" | jq -r '.ccs["SMOKE-G"].tokens[0]')
BODY=$(mktemp)
HTTP=$(curl -sS -o "$BODY" -w '%{http_code}' -X POST "$API/v1/questionarios/$TOK/respostas" \
  -H 'Content-Type: application/json' \
  -d "{\"respostas\":[{\"item_id\":\"$ITEM1\",\"valor\":1}]}")
[[ "$HTTP" == "409" ]] && ok "re-submissão HTTP 409" || fail "esperava 409, veio $HTTP"
jq -e '.detail.code == "questionario_ja_concluido"' "$BODY" >/dev/null \
  && ok "code estável questionario_ja_concluido" || fail "code errado: $(cat "$BODY")"
rm -f "$BODY"

bold "== 4. Submissão nos pequenos (SMOKE-P1 + SMOKE-P2, somam 5 no Bloco-Smoke-B) =="
N_OK=0
for cc in SMOKE-P1 SMOKE-P2; do
  for tok in $(echo "$SEED" | jq -r ".ccs[\"$cc\"].tokens[]"); do
    HTTP=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API/v1/questionarios/$tok/respostas" \
      -H 'Content-Type: application/json' \
      -d "{\"respostas\":[{\"item_id\":\"$ITEM1\",\"valor\":2}]}")
    [[ "$HTTP" == "201" ]] && N_OK=$((N_OK+1))
  done
done
[[ "$N_OK" == "5" ]] && ok "5/5 submissões pequenos 201" || fail "$N_OK/5 submissões pequenos"

bold "== 5. Agregado SMOKE-G: bucket=centro_custo, valor=SMOKE-G, n=5 =="
BODY=$(mktemp)
HTTP=$(curl -sS -b "$CJ" -o "$BODY" -w '%{http_code}' "$API/v1/respostas/agregado?centro_custo_id=$CC_G_ID")
[[ "$HTTP" == "200" ]] && ok "agregado HTTP 200" || fail "agregado HTTP $HTTP"
jq -e '.bucket.tipo == "centro_custo" and .bucket.valor == "SMOKE-G" and .n_questionarios == 5 and .supressao == null' "$BODY" >/dev/null \
  && ok "bucket centro_custo + codigo + n=5 + sem supressão" \
  || fail "agregado inesperado: $(cat "$BODY")"
jq -e '.por_dominio | length == 1 and .[0].dominio_nome == "SMOKE Demandas" and .[0].n_respostas == 10' "$BODY" >/dev/null \
  && ok "domínio SMOKE Demandas com 10 respostas (5×2)" \
  || fail "por_dominio errado: $(cat "$BODY")"
rm -f "$BODY"

bold "== 6. Agregado SMOKE-P1: bucket=bloco_predio, valor=Bloco-Smoke-B, n=5 =="
BODY=$(mktemp)
curl -sS -b "$CJ" -o "$BODY" "$API/v1/respostas/agregado?centro_custo_id=$CC_P1_ID"
jq -e '.bucket.tipo == "bloco_predio" and .bucket.valor == "Bloco-Smoke-B" and .n_questionarios == 5 and .supressao == null' "$BODY" >/dev/null \
  && ok "bucket bloco_predio + nome do bloco + n=5" \
  || fail "agregado bloco inesperado: $(cat "$BODY")"
rm -f "$BODY"

bold "== 7. Agregado SMOKE-S (zero respostas): supressão k-anonimato =="
BODY=$(mktemp)
curl -sS -b "$CJ" -o "$BODY" "$API/v1/respostas/agregado?centro_custo_id=$CC_S_ID"
jq -e '.n_questionarios == 0 and .supressao.motivo == "k_anonimato_insuficiente" and .supressao.minimo_requerido == 5 and .por_dominio == []' "$BODY" >/dev/null \
  && ok "supressão devolvida com motivo estável e por_dominio vazio" \
  || fail "supressão errada: $(cat "$BODY")"
rm -f "$BODY"

bold "== 8. Agregado sem cookie devolve 401 =="
HTTP=$(curl -sS -o /dev/null -w '%{http_code}' "$API/v1/respostas/agregado?centro_custo_id=$CC_G_ID")
[[ "$HTTP" == "401" ]] && ok "gate de autenticação OK (401)" || fail "esperava 401, veio $HTTP"

bold "== Resumo =="
if [[ $FALHAS -eq 0 ]]; then
  printf '\033[1;32mTodos os checks passaram.\033[0m\n'
  exit 0
else
  printf '\033[1;31m%d check(s) falharam.\033[0m\n' "$FALHAS"
  exit 1
fi

#!/usr/bin/env bash
# Smoke test E2E do fluxo de import de centros de custo contra o stack rodando.
# Diferente dos testes unitários (Vitest), este bate na API real e no banco real.
# Roda a partir da raiz de `plataforma/`. Requer curl + jq + docker compose.

set -euo pipefail

API="${API_BASE:-http://localhost:8000}"
PG_USER="${POSTGRES_USER:-plataforma}"
PG_DB="${POSTGRES_DB:-plataforma}"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; FALHAS=$((FALHAS+1)); }

FALHAS=0

CSV_OK_JSON='{"itens":[
  {"codigo":"ROOT","nome":"HCPA","codigo_pai":null,"total_colaboradores":0},
  {"codigo":"ADM","nome":"Administração","codigo_pai":"ROOT","total_colaboradores":120,"bloco_predio":"Prédio Central"},
  {"codigo":"ENF-3A","nome":"Enfermaria 3A","codigo_pai":"ROOT","total_colaboradores":85,"bloco_predio":"Bloco A"}
]}'

CSV_BAD_JSON='{"itens":[
  {"codigo":"ORFAO","nome":"Setor órfão","codigo_pai":"NAO-EXISTE","total_colaboradores":10}
]}'

bold "== Preparação =="
docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" \
  -c "TRUNCATE centros_custo CASCADE;" >/dev/null
ok "banco zerado"

bold "== 1. Preview de payload válido =="
PREVIEW_OK=$(curl -sS -X POST "$API/v1/centros-custo/import/preview" \
  -H 'Content-Type: application/json' -d "$CSV_OK_JSON")
echo "$PREVIEW_OK" | jq -e '.valido == true' >/dev/null \
  && ok "preview.valido=true" || fail "preview.valido != true: $PREVIEW_OK"
echo "$PREVIEW_OK" | jq -e '.novos | length == 3' >/dev/null \
  && ok "preview.novos.length=3" || fail "preview.novos errado: $PREVIEW_OK"

bold "== 2. Commit do payload válido =="
COMMIT_OK=$(curl -sS -X POST "$API/v1/centros-custo/import/commit" \
  -H 'Content-Type: application/json' -d "$CSV_OK_JSON")
echo "$COMMIT_OK" | jq -e '.criados == 3 and .atualizados == 0' >/dev/null \
  && ok "commit.criados=3 atualizados=0" || fail "commit errado: $COMMIT_OK"

bold "== 3. Idempotência (re-commit do mesmo payload) =="
COMMIT_2=$(curl -sS -X POST "$API/v1/centros-custo/import/commit" \
  -H 'Content-Type: application/json' -d "$CSV_OK_JSON")
echo "$COMMIT_2" | jq -e '.criados == 0 and .atualizados == 3' >/dev/null \
  && ok "re-commit.criados=0 atualizados=3" || fail "re-commit errado: $COMMIT_2"

bold "== 4. Preview de payload inválido (codigo_pai inexistente) =="
PREVIEW_BAD=$(curl -sS -X POST "$API/v1/centros-custo/import/preview" \
  -H 'Content-Type: application/json' -d "$CSV_BAD_JSON")
echo "$PREVIEW_BAD" | jq -e '.valido == false' >/dev/null \
  && ok "preview.valido=false" || fail "preview.valido != false: $PREVIEW_BAD"
echo "$PREVIEW_BAD" | jq -e '.erros[0].erro | test("NAO-EXISTE")' >/dev/null \
  && ok "erro cita 'NAO-EXISTE'" || fail "mensagem errada: $PREVIEW_BAD"

bold "== 5. Commit rejeitado para payload inválido (HTTP 422) =="
HTTP=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "$API/v1/centros-custo/import/commit" \
  -H 'Content-Type: application/json' -d "$CSV_BAD_JSON")
[[ "$HTTP" == "422" ]] \
  && ok "commit inválido retornou HTTP 422" || fail "esperava 422, veio $HTTP"

bold "== 6. Verificação no banco =="
COUNT=$(docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tA \
  -c "SELECT COUNT(*) FROM centros_custo;")
[[ "$COUNT" == "3" ]] \
  && ok "banco tem 3 registros" || fail "esperava 3 no banco, veio $COUNT"

ORFAO_COUNT=$(docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tA \
  -c "SELECT COUNT(*) FROM centros_custo WHERE codigo = 'ORFAO';")
[[ "$ORFAO_COUNT" == "0" ]] \
  && ok "registro inválido NÃO foi persistido" || fail "ORFAO no banco! ($ORFAO_COUNT)"

bold "== Resumo =="
if [[ $FALHAS -eq 0 ]]; then
  printf '\033[1;32mTodos os checks passaram.\033[0m\n'
  exit 0
else
  printf '\033[1;31m%d check(s) falharam.\033[0m\n' "$FALHAS"
  exit 1
fi

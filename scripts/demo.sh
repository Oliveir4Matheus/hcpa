#!/usr/bin/env bash
# Roteiro de demo técnica HCPA — reunião 2026-05-15.
# Cada passo é interativo: aperte ENTER para avançar (ou rode com DEMO_AUTO=1 para correr seco).
#
# Pré-requisitos: docker compose disponível, rodar a partir da raiz de `plataforma/`.

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
WEB_BASE="${WEB_BASE:-http://localhost:3000}"
PG_USER="${POSTGRES_USER:-plataforma}"
PG_DB="${POSTGRES_DB:-plataforma}"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
title() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

pause() {
  if [[ "${DEMO_AUTO:-0}" == "1" ]]; then return 0; fi
  printf '\033[2m▶ ENTER para continuar...\033[0m '
  read -r _
}

run() {
  bold "\$ $*"
  pause
  eval "$@"
}

# --------------------------------------------------------------------
title "Passo 0 — checar local de execução"
if [[ ! -f docker-compose.yml ]]; then
  echo "ERRO: rode a partir da raiz de plataforma/ (cd plataforma)." >&2
  exit 1
fi
dim "OK — docker-compose.yml encontrado."

# --------------------------------------------------------------------
title "Passo 1 — subir a stack"
run "docker compose up -d"
run "docker compose ps"
dim "Esperado: postgres, redis, api → healthy; web → Up."

# --------------------------------------------------------------------
title "Passo 2 — liveness / readiness"
run "curl -sS -o /dev/null -w 'GET /healthz       → %{http_code}\\n' $API_BASE/healthz"
run "curl -sS -o /dev/null -w 'GET /v1/healthz    → %{http_code}\\n' $API_BASE/v1/healthz"
run "curl -sS $API_BASE/v1/readyz | jq ."
dim "readyz valida conexão async com o Postgres."

# --------------------------------------------------------------------
title "Passo 3 — schema materializado no banco"
run "docker compose exec -T postgres psql -U $PG_USER -d $PG_DB -c '\\dt'"
dim "Esperado: 10 tabelas + alembic_version."

# --------------------------------------------------------------------
title "Passo 4 — API de import de centros de custo (2 fases)"

bold "4a) Preview com payload válido (raiz + 2 filhos)"
cat <<'JSON' > /tmp/cc_preview_ok.json
{
  "itens": [
    {"codigo": "ROOT",     "nome": "HCPA",                "codigo_pai": null,   "total_colaboradores": 0},
    {"codigo": "ADM",      "nome": "Administração",       "codigo_pai": "ROOT", "total_colaboradores": 120, "bloco_predio": "Prédio Central"},
    {"codigo": "ENF-3A",   "nome": "Enfermaria 3A",       "codigo_pai": "ROOT", "total_colaboradores": 85,  "bloco_predio": "Bloco A"}
  ]
}
JSON
run "curl -sS -X POST $API_BASE/v1/centros-custo/import/preview \
  -H 'Content-Type: application/json' \
  -d @/tmp/cc_preview_ok.json | jq ."
dim "Esperado: valido=true, novos=[ROOT, ADM, ENF-3A], erros=[]."

bold "4b) Preview com payload inválido (codigo_pai inexistente)"
cat <<'JSON' > /tmp/cc_preview_bad.json
{
  "itens": [
    {"codigo": "ORFAO", "nome": "Setor órfão", "codigo_pai": "NAO-EXISTE", "total_colaboradores": 10}
  ]
}
JSON
run "curl -sS -X POST $API_BASE/v1/centros-custo/import/preview \
  -H 'Content-Type: application/json' \
  -d @/tmp/cc_preview_bad.json | jq ."
dim "Esperado: valido=false, erros[].erro mencionando codigo_pai."

bold "4c) Commit do payload válido (persiste no PG)"
run "curl -sS -X POST $API_BASE/v1/centros-custo/import/commit \
  -H 'Content-Type: application/json' \
  -d @/tmp/cc_preview_ok.json | jq ."
dim "Esperado: criados=3, atualizados=0."

bold "4d) Re-commit do MESMO payload (upsert idempotente)"
run "curl -sS -X POST $API_BASE/v1/centros-custo/import/commit \
  -H 'Content-Type: application/json' \
  -d @/tmp/cc_preview_ok.json | jq ."
dim "Esperado: criados=0, atualizados=3."

bold "4e) Confirmar no banco"
run "docker compose exec -T postgres psql -U $PG_USER -d $PG_DB -c \"
  SELECT cc.codigo,
         cc.nome,
         pai.codigo AS codigo_pai,
         cc.total_colaboradores
  FROM centros_custo cc
  LEFT JOIN centros_custo pai ON pai.id = cc.centro_custo_pai_id
  ORDER BY cc.codigo;
\""

# --------------------------------------------------------------------
title "Passo 5 — front: home + estrutura de rotas"
bold "Abra no navegador:"
echo "  $WEB_BASE/            → landing com 3 cards (Respondente / Painel / Admin)"
echo "  $WEB_BASE/respondente → placeholder Sprint 2"
echo "  $WEB_BASE/painel      → placeholder Sprint 4"
echo "  $WEB_BASE/admin       → placeholder Sprint 1 (próximo entregável: upload CSV)"
pause

# --------------------------------------------------------------------
title "Fim do roteiro"
dim "Limpeza opcional: docker compose down  (mantém volumes)"
dim "                  docker compose down -v (zera o banco)"

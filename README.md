# Plataforma HCPA — DartenMind

Plataforma de avaliação de fatores de risco psicossocial (NR-1 / COPSOQ II-Br).
Cliente principal: HCPA, via parceria DartenMind (Suboperadora) ↔ HMind (Operadora).

> **Status:** Sprint 0 — scaffold inicial. Sem lógica de negócio ainda.
> Documentação completa do projeto está na pasta-pai (`../*.md`).

---

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Next.js 15 + Tailwind v4 (App Router, PWA) |
| Backend | Python 3.12 + FastAPI + Pydantic v2 |
| Banco | PostgreSQL 16 + pgcrypto |
| Cache / fila | Redis 7 |
| Migrations | Alembic (async) |
| Orquestração local | Docker Compose |
| Reverse proxy (prod) | Traefik (via Coolify) |
| Hospedagem (prod) | VPS BR + Coolify |

---

## Estrutura

```
plataforma/
├── apps/
│   ├── api/                  FastAPI + SQLAlchemy async + Alembic
│   └── web/                  Next.js 15 + Tailwind
├── infra/
│   └── postgres/init.sql     Extensões pgcrypto / uuid-ossp
├── docker-compose.yml        Orquestração dev (api + web + postgres + redis)
├── .env.example              Template de variáveis
└── README.md
```

---

## Quickstart (dev local)

Pré-requisitos: Docker + Docker Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Após subir:

- API:  http://localhost:8000/healthz
- Web:  http://localhost:3000
- Postgres: localhost:5432  (user/db: ver `.env`)
- Redis: localhost:6379

Para rodar fora do Docker (opcional, requer Python 3.12 + Node 20+):

```bash
# API
cd apps/api
uv sync                       # ou: pip install -e .
uv run uvicorn app.main:app --reload

# Web
cd apps/web
pnpm install                  # ou npm / yarn
pnpm dev
```

---

## Migrations (Alembic)

```bash
# Dentro do container da API
docker compose exec api alembic revision -m "descricao" --autogenerate
docker compose exec api alembic upgrade head
```

---

## Roadmap (cronograma contratual)

| Sprint | Janela | Foco |
|---|---|---|
| 0 | até 28/05 | Repo, infra, scaffolds, schema Salesforce |
| 1 | 01/06 – 07/06 | Modelagem PG (10 tabelas), import CSV CC, Connected App |
| 2 | 08/06 – 14/06 | Identidade & anonimato, descarte de `colaborador_import` |
| 3 | 15/06 – 21/06 | Coleta, totem PWA, smoke 200 |
| 4 | 22/06 – 28/06 | Painel SSE, IMRs absolutos, exportação assinada |
| 5 | 29/06 – 05/07 | Resultados, lembretes, carga 1.000+ |
| 6 | 06/07 – 12/07 | Hardening, pentest, RIPD, treinamento |
| **TAIS** | **15/07** | Plataforma 100% operacional |

Detalhes: `../hcpa-planejamento-tecnico-v2.md`.

---

## Princípios arquiteturais

1. **Anonimato by design** — identidade só serve para liberar acesso; tabela `colaborador_import` é descartada após a distribuição de senhas.
2. **Auditabilidade total** — toda ação admin gera log imutável (`auditoria`).
3. **Resiliência operacional** — 24/7 durante a coleta; backup contínuo.
4. **Segregação Salesforce ↔ Plataforma** — Salesforce só recebe agregados (Matriz de Riscos, status, link/PDF do laudo).
5. **Reaproveitamento estratégico** — base do produto NR-1 da HMind para próximos editais.

# Deploy via Coolify

Runbook para subir a Plataforma HCPA (api + web + postgres + redis) em
homolog e produção usando o Coolify auto-hospedado em
`coolify.dartenmind.com.br`.

> Domínio raiz: `dartenmind.com.br`. `<IP_VPS>` é o IP público do
> servidor que hospeda o Coolify (mesmo IP para onde
> `coolify.dartenmind.com.br` já resolve).

---

## 0. Pré-requisitos

- Coolify ativo em `coolify.dartenmind.com.br` (já feito, server
  `localhost` healthy).
- Permissão para criar entradas DNS em `dartenmind.com.br`.
- Conta GitHub para repo privado.
- `openssl` local (para gerar segredos).

Stack do servidor: assumir mínimo 4 vCPU / 8 GB RAM para homolog + prod
+ os 23 apps já existentes do painel. Conferir `htop` / `df -h` no VPS
antes de subir o primeiro deploy.

---

## 1. Push do código para um repo Git remoto

Coolify puxa o código por Git. O repo local em `plataforma/` ainda não
tem remote.

```bash
# Criar repo privado no GitHub (uma vez)
#   Nome sugerido: dartenmind/plataforma-hcpa  (private)

# Apontar o remote local
cd plataforma
git remote add origin git@github.com:<seu-usuario>/plataforma-hcpa.git
git branch -M main
git push -u origin main

# Criar branch staging que vai para homolog
git checkout -b staging
git push -u origin staging
git checkout main
```

> Se ainda não tem chave SSH no GitHub, gerar via
> `ssh-keygen -t ed25519 -C "<seu email>"` e adicionar
> `~/.ssh/id_ed25519.pub` em **GitHub → Settings → SSH keys**.

---

## 2. DNS

No painel do registrador, criar 4 entradas tipo **A** (todas apontando
para `<IP_VPS>`):

| Subdomínio (homolog) | Subdomínio (prod)   |
|----------------------|---------------------|
| `app.hcpa-stg`       | `app.hcpa`          |
| `api.hcpa-stg`       | `api.hcpa`          |

TTL 300 s (5 min). Aguardar propagação (`dig api.hcpa-stg.dartenmind.com.br +short`).

---

## 3. Coolify — Source GitHub

1. **Sources → Add Source → GitHub App**
2. Seguir o fluxo (cria GitHub App + instala no repo `plataforma-hcpa`).
3. Confirmar que o Coolify lista o repo após instalação.

> Alternativa sem GitHub App: usar deploy key SSH. Em
> **Sources → Add Source → Public/Private Repository**, colar o
> `id_ed25519.pub` gerado pelo Coolify na aba **Deploy Keys** do repo
> no GitHub.

---

## 4. Coolify — Projeto + Ambientes

1. **Projects → New Project** → `hcpa`.
2. Dentro de `hcpa`, criar dois Environments: `staging` e `production`.

> Ambos vão usar o mesmo servidor; a separação é lógica (env vars
> diferentes, FQDNs diferentes, e podem apontar para branches Git
> diferentes — staging↔staging, production↔main).

---

## 5. Recurso `hcpa-app-staging` (homolog)

Em **hcpa → staging**:

1. **+ New → Resource → Docker Compose Empty** (ou "from Git").
2. **Source** → o repo conectado no passo 3.
3. **Branch** → `staging`.
4. **Docker Compose Location** → `docker-compose.prod.yml`.
5. **Domains** (aba do recurso, depois do primeiro save):
   - `api` (porta 8000) → `https://api.hcpa-stg.dartenmind.com.br`
   - `web` (porta 3000) → `https://app.hcpa-stg.dartenmind.com.br`

   Coolify popula automaticamente `SERVICE_FQDN_API_8000` e
   `SERVICE_FQDN_WEB_3000` no compose com os valores acima.

6. **Environment Variables** (aba do recurso):

   | Variável               | Valor                                | Marcar como Secret |
   |------------------------|--------------------------------------|--------------------|
   | `POSTGRES_DB`          | `plataforma`                         | não                |
   | `POSTGRES_USER`        | `plataforma`                         | não                |
   | `POSTGRES_PASSWORD`    | `openssl rand -base64 32`            | ✅                  |
   | `API_ENV`              | `staging`                            | não                |
   | `API_LOG_LEVEL`        | `INFO`                               | não                |
   | `API_SECRET_KEY`       | `openssl rand -hex 32`               | ✅                  |
   | `ENCRYPTION_KEY`       | `openssl rand -base64 32`            | ✅                  |

   > Gere cada secret separadamente — **NÃO reuse `ENCRYPTION_KEY`
   > entre homolog e prod**. Cada ambiente cifra dados em repouso com
   > sua própria chave.

7. **Deploy**. Acompanhar logs até `api` e `web` ficarem `healthy`.

8. **Bootstrap do operador admin** (uma vez):

   ```bash
   # No painel Coolify, abrir o Terminal do serviço `api`:
   python -m scripts.create_operador \
     --email admin@dartenmind.com.br --senha '<senha forte>' --nome Admin
   ```

9. **Smoke E2E**:

   ```bash
   # Em local:
   curl -i https://api.hcpa-stg.dartenmind.com.br/healthz
   curl -i -X POST -H "Content-Type: application/json" \
     -d '{"email":"admin@dartenmind.com.br","senha":"<senha>"}' \
     https://api.hcpa-stg.dartenmind.com.br/v1/auth/login
   # Abrir https://app.hcpa-stg.dartenmind.com.br/login no navegador.
   ```

---

## 6. Recurso `hcpa-app-production` (prod)

Repetir o passo 5 dentro de **hcpa → production**, com 3 diferenças:

- **Branch**: `main`
- **Domains**: `api.hcpa.dartenmind.com.br` e `app.hcpa.dartenmind.com.br`
- **Env vars**:
  - `API_ENV=production`
  - `POSTGRES_PASSWORD`, `API_SECRET_KEY`, `ENCRYPTION_KEY` →
    **gerar novos**, não reusar de staging.
  - Marcar `Auto Deploy` como **manual** (não fazer push direto em
    prod automaticamente; sempre via PR + tag).

---

## 7. Deploy contínuo

- **Staging**: habilitar `Auto Deploy` no Coolify → cada push em
  `staging` redepliega o homolog automaticamente.
- **Production**: deploy manual via botão "Redeploy" depois de mergear
  PR em `main`.

Fluxo recomendado:

```
feature/x ──► staging  (auto deploy homolog)
               │
               ▼ PR
              main     (deploy manual prod)
```

---

## 8. Operações comuns

### Rodar migrations manualmente

Não é necessário — o `command` do serviço `api` no `docker-compose.prod.yml`
roda `alembic upgrade head` antes de subir o uvicorn em todo restart.

Se precisar rodar fora de um deploy:

```bash
# Terminal do serviço api no Coolify
alembic upgrade head
```

### Backup do Postgres

O volume `postgres_data` é gerenciado pelo Coolify. Para backups
versionados, ativar **Backups** no Resource (Coolify → Backups), com
schedule diário e retenção 14 dias. Destino S3-compatible recomendado
(Wasabi, Backblaze B2).

### Rotacionar `ENCRYPTION_KEY`

Plano por enquanto: **bloquear**. A camada `app.core.crypto` reserva
um version byte (`CURRENT_KEY_VERSION=1`) que permite rotação no
futuro com migration explícita. Documentar e executar como tarefa
de Sprint própria.

### Trocar segredos

Coolify → Resource → Environment Variables → editar → **Redeploy**.

---

## 9. Limitações conhecidas

1. **Postgres dentro do compose**: simples mas não é o padrão
   production-grade do Coolify. Em Sprint futura, migrar para um
   **Database Resource** dedicado (snapshot/backup builtin, isolado
   da aplicação).
2. **Sem CDN**: `web` serve direto via Traefik. Aceitável para o
   volume HCPA (poucos colaboradores acessando o painel).
3. **Sem TOTP no painel**: operadores com TOTP ativo precisam
   desabilitar via admin para entrar. Backlog Sprint 1+.
4. **`bucket.valor` devolve UUID** em agregações por centro de
   custo; o painel já trata mostrando `codigo · nome` via prop.
   Backlog do backend.

---

## 10. Checklist final antes de chamar de homolog "pronto"

- [ ] DNS A records criados e propagados (4 entradas).
- [ ] Repo `plataforma-hcpa` no GitHub, branches `main` e `staging`
      sincronizados.
- [ ] Source conectada no Coolify (GitHub App ou Deploy Key).
- [ ] Resource `staging` deployado com saúde verde nos 4 serviços.
- [ ] `https://api.hcpa-stg.dartenmind.com.br/healthz` retorna 200.
- [ ] `https://app.hcpa-stg.dartenmind.com.br/login` carrega e aceita login.
- [ ] Operador admin criado via terminal do Coolify.
- [ ] Submissão pública de questionário testada com token real.
- [ ] Backups configurados (Postgres) com schedule diário.

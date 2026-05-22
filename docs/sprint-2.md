# Sprint 2 — Resumo de Alterações

## Visão geral

Esta sprint entregou o pipeline completo de distribuição de credenciais aos colaboradores: desde o import com cifragem de PII, passando pela geração individual de senhas, até o descarte irreversível após a entrega. Paralelamente, o fluxo de autenticação foi expandido com suporte a TOTP no painel e autenticação separada para respondentes.

---

## Backend (API)

### Migrations

| Migration | O que faz |
|---|---|
| `operadores_trigger_atualizado_em` | Trigger que atualiza `atualizado_em` automaticamente nos operadores |
| `colaborador_import_senha_nullable` | Torna `senha_hash` nullable em `colaborador_import` (senha gerada só na distribuição) |
| `credencial_lookup_e_lembrete_sem_fk` | Remove FK de `credencial` para `colaborador_import`, desacoplando identidade de credencial |

### Novos endpoints

#### Autenticação de respondentes — `POST /v1/auth/respondente`
- Cookie separado (`hcpa_resp_sessao`), TTL 48h, sem TOTP, sem revogação manual
- Ciclo de vida completamente independente da autenticação de operadores

#### Import de colaboradores
- `POST /v1/colaboradores/import/preview` — valida o payload sem persistir nada, classifica em `novos` / `atualizados` / `erros`
- `POST /v1/colaboradores/import/commit` — persiste com cifragem AES-256-GCM de PII (nome, email), resolve FK de centro de custo pelo `codigo`

#### Distribuição de credenciais — `POST /v1/colaboradores/distribuir`
- Gera senha aleatória legível por colaborador (alfabeto sem ambíguos, ~63 bits de entropia, argon2id no banco)
- Senha em texto claro aparece **apenas na resposta HTTP** — nunca é persistida
- Operador é responsável pela entrega física e por chamar `/descartar` ao concluir

#### Descarte — `POST /v1/colaboradores/descartar`
- Ação **irreversível**: zera `colaborador_import` após a distribuição confirmada
- Pré-condição: nenhum colaborador pode estar em status `pendente`
- Requer `{ "confirmar": true }` no body para evitar descarte acidental
- `credencial` sobrevive intacta (hash + CC, sem elo com identidade)

### Novos services

- **`colaborador_import`** — preview e aplicação do import, validação de duplicatas e FK de CC
- **`descarte`** — descarte com pré-condição e idempotência (tabela já vazia → no-op auditado)
- **`distribuicao`** — geração de senhas, criação de `Credencial`, atualização de status para `distribuida`
- **`respondente_auth`** — autenticação de respondentes via senha única, sessão com TTL separado

### Novos schemas

- `colaborador` — `ColaboradorImportItem`, `ColaboradorImportPreview`, `ColaboradorImportResult`, `DescarteRequest`, `DistribuicaoResult`
- `respondente` — `RespondenteLoginRequest`, `RespondenteLoginResponse`
- `resposta` — ajustes para suportar o pipeline e2e

### Testes

Cobertura adicionada em:

| Arquivo | O que testa |
|---|---|
| `test_spec_anonimato.py` | Garantias de anonimato nas respostas |
| `test_spec_anti_enumeracao.py` | Proteção contra enumeração de credenciais |
| `test_spec_auditabilidade.py` | Trilha de auditoria em todas as ações sensíveis |
| `test_spec_k_anonimato.py` | Supressão por k-anonimato no agregado |
| `test_spec_pipeline_e2e.py` | Pipeline completo: import → distribuição → resposta → agregado |
| `test_spec_schema_invariants.py` | Invariantes do schema de banco |
| `test_colaboradores_import.py` | Import com validação de CC e duplicatas |
| `test_colaboradores_distribuicao.py` | Geração de senhas e atualização de status |
| `test_colaboradores_descarte.py` | Descarte com pré-condição e idempotência |
| `test_respondente_auth.py` | Login de respondente e gestão de sessão |
| `test_centros_custo.py` | Melhorias nos testes do import de CC |
| `test_questionario_criar.py` | Criação de questionários |

---

## Frontend (Web)

### Autenticação server-side — `app/_lib/auth-server.ts` (novo)
- Helper RSC com `exigirOperador()`: lê o cookie de sessão, chama `/v1/auth/me` diretamente via `API_URL` e redireciona para `/login` em caso de 401
- Usado no topo de páginas protegidas (admin, painel)

### Página admin protegida — `app/admin/page.tsx`
- Agora é `async` e chama `exigirOperador()` antes de renderizar
- Adicionado `metadata` com título da página

### Client de centros de custo — `app/admin/_lib/centros-custo.ts`
- Migrado de `NEXT_PUBLIC_API_URL` direto para o proxy `/api/*` (same-origin, cookie automático)
- Classe `CentrosCustoError` com `code` estável (`nao_autenticado`, `payload_invalido`, etc.)
- Tratamento de 401 com redirecionamento para `/login`

### Fluxo TOTP — `app/login/_components/TotpForm.tsx` (novo)
- Formulário de verificação TOTP exibido após o login com senha quando o operador tem TOTP habilitado
- Input numérico com `inputMode="numeric"`, `autoComplete="one-time-code"`, foco automático
- Botão "Voltar" chama `onCancelar` para retornar ao form de senha
- Em caso de sucesso, navega para `/painel`

### Login — `app/login/_lib/auth-api.ts`
- Adicionada função `postTotpVerify(codigo)` — `POST /api/v1/auth/totp/verify`
- Refatorado `lerErroOuFalhar` como helper compartilhado entre `postLogin` e `postTotpVerify`

### Scripts
- `demo.sh` e `smoke-upload.sh` atualizados para cobrir os novos fluxos da sprint

---

## O que falta

Falta apenas rodarmos **todos os testes** para garantir que está tudo ok — tanto os novos spec tests quanto a suite completa de integracao, para confirmar que nenhuma regressão foi introduzida nos fluxos existentes.

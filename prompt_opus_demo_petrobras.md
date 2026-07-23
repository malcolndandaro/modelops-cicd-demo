# Prompt — Adaptar bimbo_demo para demo de CI/CD ML/AI (Petrobras)

## Contexto

Sou SSA na Databricks e tenho uma demo **amanhã** para o time de AI/ML da Petrobras. O pedido deles: um CI/CD de ponta a ponta para assets de ML/AI no Databricks com **Databricks Asset Bundles + promoção via Git (dev/staging/prod)**, **MLflow registry/versionamento/promoção**, e um **gate de validação por IA/LLM que aprova ou bloqueia a promoção** (qualidade do modelo, evaluation e checks de código/config), além de best practices que eles possam adotar.

Você está trabalhando no clone local do repo `bimbo_demo` (github.com/malcolndandaro/bimbo_demo). Ele já implementa ~80% do padrão, mas para um pipeline de **Data Engineering** ("bakery"). Sua missão é adaptá-lo para uma narrativa de **ML clássico com promoção de modelo**, adicionando um segundo gate de IA na promoção, e tornando a demo **resetável e repetível**.

**Antes de escrever qualquer código: leia `CLAUDE.md`, `DEMO.md`, `README.md` e explore `bimbops_reviewer/`, `resources/`, `.github/workflows/` e `databricks.yml` para entender a arquitetura existente.** Reuse os padrões do repo (auth, identidade do bot, estrutura de CI shells, ResponsesAgent, Vector Search) em vez de reinventar.

## Filosofia

**Quick and dirty, mas funcionando.** Não é código de produção: sem abstrações novas, sem refactors, sem testes além do mínimo que já existe. Cada linha precisa justificar sua existência pela demo de amanhã. Porém: tudo que aparece ao vivo precisa ser confiável e o reset precisa ser idempotente.

## O que já existe e NÃO deve ser quebrado

- **BimbOps Reviewer**: MLflow `ResponsesAgent` servido em Model Serving (endpoint `bimbops-reviewer`), aterrado no handbook (`bimbops_handbook/`, 22 regras) via Vector Search, usando `databricks-claude-sonnet-4-5` no AI Gateway. Não refatore o core do agente (`review_core.py`).
- **Workflows**: `pr-checks.yml` (Ruff + sqlfluff + bundle validate), `bimbops-review.yml` (review + Check Run com gate por severidade), `bimbops-fix.yml` (`/bimbops-fix`), `deploy.yml` (post-merge dev → gate qa → gate prd via GitHub Environments).
- **Job `bimbops_agent_lifecycle`**: index do handbook → registro UC → deploy → eval. Use-o para reindexar após mudar o handbook.
- **Auth**: OAuth M2M para Databricks; jobs que tocam o workspace rodam em runner self-hosted. Secrets em GitHub Actions secrets, config não-secreta em repo variables. **Nunca commite segredos nem hostnames de workspace.**

## Tarefas (em ordem de prioridade)

### T1 — Pipeline de ML clássico (substitui o bakery como protagonista)

1. Crie `src/ml/train.py`: modelo sklearn simples de previsão de demanda da padaria (mantém a narrativa Bimbo/dados existentes de `data/seed_bakery.py`). Treino rápido (<2 min), features simples, métrica clara (ex.: MAE).
2. Hiperparâmetros e nome do modelo em um arquivo de config versionado (ex.: `src/ml/config.yml`) — a demo mostra um PR alterando esse arquivo.
3. Job DAB `model_training_job` (novo arquivo em `resources/jobs/`), **serverless**, com tasks:
   - `train`: treina e loga run no MLflow (MLflow >= 3, tracking no workspace).
   - `register`: registra no Unity Catalog como `<catalog>.<schema>.demand_forecaster` (catálogo por target: dev/qa/prd conforme padrão do `databricks.yml`). Nova versão recebe alias `@challenger`.
   - `promotion_gate` (T2, abaixo).
   - `promote`: se o gate aprovar, move alias `@champion` para a versão challenger.
4. Teste de regressão de métrica em `tests/` (ex.: MAE máximo aceitável hardcoded) — ele existe para ser "esquecido" no bad-PR da demo.
5. Plugue o job no `deploy.yml` no estágio apropriado (após deploy dev, dentro do fluxo de staging/qa), seguindo o padrão existente do workflow.

Use **aliases de UC (`@champion`/`@challenger`)** — não use stages do workspace registry (deprecado). Deixe isso explícito em comentários, pois o cliente vai perguntar sobre "stage transitions".

### T2 — AI Promotion Gate (item mais importante do request do cliente)

Notebook/script `src/ml/promotion_gate.py` executado como task do `model_training_job`:

1. Coleta: métricas do challenger vs `@champion` atual (via `MlflowClient`), diff do config de treino, e (se barato de obter) resumo do último PR mergeado.
2. Chama o LLM (mesmo endpoint `databricks-claude-sonnet-4-5` via AI Gateway, mesmo padrão de client do reviewer) com as regras de ML do handbook no prompt (pode injetar as regras direto no prompt — não precisa de Vector Search aqui, quick and dirty).
3. Saída estruturada JSON: `{"decision": "APPROVE" | "BLOCK", "findings": [...], "justification": "..."}`. Parse defensivo (strip de fences markdown).
4. `APPROVE` → task `promote` roda (use dependência condicional de task ou raise para falhar o job). `BLOCK` → job falha com o parecer completo no output/log, e (se simples) comenta no commit/PR via GitHub API reusando o client de `bimbops_reviewer/ci/`.
5. Instrumente com MLflow 3 tracing (`mlflow.start_span` por etapa + autolog nas chamadas LLM) — os traces aparecem na demo.
6. Caso especial primeira execução: se não existe `@champion`, aprova automaticamente (bootstrap).

### T3 — Modo fix abre PR em vez de commit direto

Modifique `bimbops_reviewer/ci/fix_pr.py` (e `bimbops-fix.yml` se necessário): em vez de push direto na branch do PR:

1. `git checkout -b bimbops-fix/pr-<n>-<run_id>` a partir da head branch do PR.
2. Aplica o rewrite (lógica existente inalterada), commit com a identidade do bot já configurada, push.
3. `POST /repos/{owner}/{repo}/pulls` com `base = head branch do PR original` e `head = bimbops-fix/...`, body linkando o comentário `/bimbops-fix` que originou.
4. Comenta no PR original com o link do PR de fix.

Mudança mínima — preserve auth, identidade e tratamento de erros existentes.

### T4 — Regras de ML no handbook

Adicione 4–5 regras ao `bimbops_handbook/` seguindo o formato das 22 existentes. Sugestões:

- Mudança de hiperparâmetro/feature exige atualização do teste de regressão de métrica no mesmo PR.
- Modelos só no Unity Catalog registry; alias `@champion` só é movido pelo pipeline, nunca manualmente.
- Promoção exige challenger com métrica >= champion (ou degradação justificada e aprovada).
- Config de treino não pode referenciar catálogo de outro ambiente (variação da regra cross-env existente).

Depois rode/documente o comando para reindexar (`databricks bundle run bimbops_agent_lifecycle -t dev`).

### T5 — bad-pr de ML (dois cenários)

Na pasta `bad-pr/`, seguindo o padrão existente, crie **dois patches/variações**:

1. **`bad-pr/ml-review-blocker/`**: muda hiperparâmetro no `config.yml` sem atualizar o teste de regressão + referência a catálogo `prd` em config de dev → pego pelo **Reviewer** (Gate 1) no PR.
2. **`bad-pr/ml-gate-blocker/`**: mudança "limpa" no código (passa no review) mas que degrada a métrica do modelo (ex.: remove feature importante ou reduz `n_estimators` drasticamente) → passa no PR, mas o **Promotion Gate** (Gate 2) bloqueia. Este cenário demonstra por que o gate de promoção existe.

### T6 — Reset da demo

`scripts/reset_demo.sh` (bash, usando `gh` CLI + `databricks` CLI + python inline para MLflow), idempotente, <1 min:

1. Fecha PRs abertos com label `demo`; deleta branches `demo/*` e `bimbops-fix/*` no remoto.
2. Recria branch `demo/ml-change` a partir de `main` aplicando o patch de `bad-pr/ml-review-blocker/` (e opcionalmente `demo/ml-degraded` com o segundo patch); abre os PRs com label `demo` (ou deixa um `--open-prs` opcional).
3. Unity Catalog: deleta todas as versões do modelo exceto v1; garante alias `@champion` → v1 e remove `@challenger`.
4. Não toca `main`. Se algum passo do roteiro exigir merge ao vivo, use uma branch `release-demo` como base dos PRs e o reset faz `git reset --hard` nela para o commit inicial (decida o mais simples e documente).
5. `set -e`, mensagens claras de progresso, e checagem final imprimindo o estado (PRs abertos, versões do modelo, aliases).

### T7 — Runbook

Atualize `DEMO.md` com o novo roteiro (em português), incluindo: pré-checks (endpoint do gateway vivo, runner self-hosted online, reset rodado), o passo a passo dos dois cenários, tempos esperados de cada etapa, e plano B para cada ponto de falha (ex.: se o fix demorar, ter o PR de fix pré-criado numa branch de backup).

## Roteiro-alvo da demo (para orientar suas decisões)

1. Reset rodado antes. Estado: modelo v1 `@champion` no UC.
2. Abro PR do cenário 1 → linters passam, **Reviewer bloqueia** citando handbook.
3. Comento `/bimbops-fix` → **agente abre PR contra a branch do meu PR** → mergeio os dois.
4. Deploy roda: treina v2 → challenger → **Promotion Gate aprova** → v2 vira `@champion`. Mostro UC + traces MLflow.
5. Cenário 2 (PR que degrada métrica): review passa, **Promotion Gate bloqueia** com justificativa. Os dois desfechos do gate ficam demonstrados.

## Restrições e notas

- MLflow >= 3 em tudo (tracing/spans, UC registry). Jobs novos serverless.
- Modelo LLM: endpoint `databricks-claude-sonnet-4-5` do AI Gateway (mesmo do reviewer). Não crie endpoints novos.
- Não renomeie targets do bundle (dev/qa/prd) nem faça rebranding "Petrobras" — só garanta que nada no conteúdo é embaraçoso; na narrativa oral qa == staging.
- Repo é público: zero segredos, zero hostnames de workspace.
- Se precisar de decisões que dependem do meu ambiente (nomes de catálogo/schema, warehouse, nome do runner), **pergunte ou deixe como variável com TODO destacado no topo do arquivo** — não invente valores.
- Ao final, liste: (a) todos os arquivos criados/modificados, (b) comandos exatos para eu validar cada tarefa (bundle validate, run do job, reset), (c) o que ficou pendente de configuração manual minha.

## Definição de pronto

- `databricks bundle validate -t dev` limpo.
- `model_training_job` roda ponta a ponta em dev: treina, registra, gate aprova (bootstrap), promove.
- `fix_pr.py` novo passa nos unit tests existentes (adapte-os se testavam o push direto).
- `reset_demo.sh` rodado duas vezes seguidas termina no mesmo estado sem erro.
- `DEMO.md` atualizado.

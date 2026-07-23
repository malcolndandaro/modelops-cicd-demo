# DEMO.md — ModelOps CI/CD — Roteiro do Demo ao Vivo (PT-BR)

> **Apresentador:** Malcoln Dandaro (Databricks)
> **Duração estimada:** ~45–60 min (dois cenários completos)
> **Workspace:** `https://dbc-967959c2-d585.cloud.databricks.com` · perfil `agentic-mlops-cicd-aws`
> **Catálogo:** `malcoln_aws_stable_catalog` · Schemas: `agentic2_mlops_dev` / `agentic2_mlops_staging` / `agentic2_mlops_prod`
> **Repo:** `github.com/malcolndandaro/modelops-cicd-demo` (público)
> **LLM:** `databricks-glm-5-2`
> **Endpoints:** `modelops-reviewer` (Gate 1), `ka-5f315d3c-endpoint` (KA do Handbook, display name `modelops-handbook-ka`)

---

## Checklist pré-demo (faça ANTES da reunião)

> Todos os itens com **[PREP]** devem estar prontos antes de abrir a sala.

- [ ] **[PREP] Runner self-hosted online.** GitHub → repo → Settings → Actions → Runners mostra o runner verde. Se estiver offline, iniciar com `./run.sh` em `~/Work/Projects/actions-runner`. **Todo job que toca o Databricks exige esse runner** (workspace VPN-only).
- [ ] **[PREP] Endpoint `modelops-reviewer` PRONTO (READY, `scale_to_zero=false`).** Verificar:
  ```bash
  DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks serving-endpoints get modelops-reviewer
  ```
  Checar `state.ready=READY`. Fazer uma chamada de aquecimento se necessário.
- [ ] **[PREP] Knowledge Assistant PRONTO.** Display name `modelops-handbook-ka`, endpoint de serving `ka-5f315d3c-endpoint`. Verificar:
  ```bash
  DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks serving-endpoints get ka-5f315d3c-endpoint
  ```
  O reviewer aponta para esse endpoint via a env var `KA_ENDPOINT` (se recriar o KA no reset, atualizar o valor).
- [ ] **[PREP] Reset executado com sucesso.** Rodar:
  ```bash
  bash scripts/reset_demo.sh
  ```
  Confirmar a saída final: PRs de demo abertos nas branches certas, `demand_forecaster` v1 com `@champion`, sem `@challenger`.
- [ ] **[PREP] GitHub Environments `qa` e `prod` configurados** com `malcolndandaro` como required reviewer (Settings → Environments).
- [ ] **[PREP] Secrets/vars presentes** no repo:
  - Secrets: `DATABRICKS_CLIENT_SECRET`, `MODELOPS_BOT_TOKEN`
  - Vars: `DATABRICKS_HOST`, `DATABRICKS_SP_CLIENT_ID`
- [ ] **[PREP] Logado no GitHub como `malcolndandaro`** no browser (EMU: aprovações e merges vão pelo UI).
- [ ] **[PREP] Gravação de backup pronta.** Por experiência própria, ter um run gravado end-to-end como plano B se algo travar ao vivo.
- [ ] **Abas de aquecimento** (opcional): MLflow Experiments, job `model_training_job`, workspace Jobs UI.

---

## Arco narrativo

> *O problema → Gate 1 bloqueia → bot corrige → Gate 2 bloqueia → o que isso significa.*

1. **O problema** (30 s): os gates atuais capturam sintaxe (linters) e plataforma (`bundle validate`), mas nada captura semântica/política — e quem valida qualidade de modelo ainda é um humano fazendo revisão manual.
2. **Cenário 1 — review-blocker:** Gate 1 bloqueia um PR que parece correto para os linters mas viola duas regras do handbook (ML-01 e ENV-01). O bot abre um PR de correção automaticamente.
3. **Merge → deploy → Gate 2 aprova** (bootstrap ou PR limpo): modelo promovido, `@champion` avança.
4. **Cenário 2 — gate-blocker:** Gate 1 passa (PR tecnicamente limpo), mas Gate 2 bloqueia porque o modelo degradou — a promoção não acontece.
5. **Take-home:** duas camadas de defesa, o humano ainda aprova, o agente é ele mesmo governado pelo pipeline.

---

## Passo a passo — Cenário 1: review-blocker (Gate 1 bloqueia)

**Duração estimada: 20–25 min**

### Passo 0 — Enquadrar o problema (~2 min)

- **Dizer:** "Os nossos gates hoje capturam *sintaxe* — Ruff, sqlfluff — e *plataforma* com `bundle validate`. O que não capturamos é o *semântico*: uma config de dev apontando para o schema de prod, ou uma mudança de hiperparâmetro sem atualizar o teste de regressão. E a validação de qualidade do modelo ainda cai na mão de um humano. Vamos ver dois gates de IA que cobrem exatamente esse espaço."
- **Esperado:** audiência alinha com o gap.

### Passo 1 — Abrir o PR review-blocker (~2 min)

- **Fazer:** abrir o PR `demo/ml-review-blocker` no browser.
- **URL:** `https://github.com/malcolndandaro/modelops-cicd-demo/pulls`
- **Dizer:** "Um dev abriu este PR aumentando `n_estimators` de 100 para 200 — parece uma melhoria inocente. Ruff, sqlfluff e `bundle validate` passam todos no verde."
- **Mostrar:** diff em `src/ml/config.yml` (n_estimators mudou) e uma linha referenciando `agentic2_mlops_prod` num contexto de dev.
- **Dizer:** "Aqui está o problema: `n_estimators` mudou mas o teste de regressão em `tests/test_demand_forecaster.py` não foi atualizado — isso viola ML-01 do handbook. E esta referência ao schema de prod a partir de um contexto dev viola ENV-01. Nenhum linter pega isso."
- **Esperado:** checks de lint/bundle **verdes**, `ModelOps Reviewer` **vermelho (BLOCKER)**.

### Passo 2 — Gate 1 posta os findings (~3 min)

- **Fazer:** rolar para a conversa do PR, mostrar o comentário do agente e o Check Run `ModelOps Reviewer` (failing).
- **Dizer:** "O revisor leu o diff, consultou o Knowledge Assistant com as regras do handbook, e postou os findings citados. Dois BLOCKERs: ML-01 (mudança de hiperparâmetro sem atualizar o teste de regressão) e ENV-01 (referência cross-env ao schema de prod). Só BLOCKER bloqueia o merge; SUGGESTION e STYLE são apenas avisos."
- **Dizer:** "A diferença chave: os linters determinísticos passaram todos. Só o agente que conhece os padrões pegou isso."
- **Esperado:** comentário com findings citados, Check Run `failure`.

### Passo 3 — `/modelops-fix` abre um PR de correção (~2 min)

- **Fazer:** no campo de comentário do PR, digitar **`/modelops-fix`** e enviar (UI, como `malcolndandaro`).
- **Dizer:** "Agora peço ao mesmo agente para corrigir. Ele vai verificar se quem comentou tem permissão de escrita, que não é um fork, que não é uma branch protegida — e então vai criar uma branch de correção e abrir um PR contra a branch deste PR."
- **Esperado:** workflow `modelops-fix` inicia no runner self-hosted. Monitorar em `https://github.com/malcolndandaro/modelops-cicd-demo/actions`.

### Passo 4 — Bot abre PR de correção, revisão fica verde (~4 min)

- **Fazer:** aguardar o PR `modelops-fix/...` aparecer aberto no repo. Apontar o link no comentário do PR original.
- **Dizer:** "O bot — com identidade própria via token no demo, GitHub App em produção — abriu um novo PR com a correção. Esse PR re-dispara o Gate 1 na branch de origem. Bucle auto-corretivo."
- **Fazer:** se o PR original re-rodar e ficar verde (Check Run `success`), mostrar.
- **Esperado:** PR de fix aberto; Check Run do PR original re-roda e fica verde.

### Passo 5 — Aprovar e fazer merge (~1 min)

- **Fazer:** aprovar o PR original (ou o de fix, dependendo do fluxo) e clicar em Merge no GitHub UI.
- **Dizer:** "O humano ainda aprova. O agente tirou o trabalho mecânico, não a decisão."
- **Esperado:** merge para `main`, aciona `deploy.yml`.

### Passo 6 — deploy-dev + Gate 2 aprova (bootstrap/run limpo) (~5–8 min)

- **Fazer:** abrir Actions → run de deploy. Monitorar `deploy-dev` e depois `train-and-promote-dev`.
- **Dizer:** "Após o merge, o pipeline faz deploy no dev e em seguida roda o `model_training_job`: treino → registro → Gate 2 → promoção. Como este é o primeiro run (ou o reset deixou só v1), o Gate 2 vai auto-aprovar no bootstrap."
- **Esperado:** `deploy-dev` verde; `model_training_job` verde; `@champion` avança para nova versão.

### Passo 7 — Aprovar gate qa (dar o botão para o cliente) (~2 min)

- **Fazer:** no run de Actions, `deploy-qa` mostra "Review pending". Clicar em Review → qa → Approve and deploy (UI).
- **Dizer (para o cliente):** "Esse botão é seu. Hoje esta validação cai na sua mão manualmente — aqui é um gate explícito, auditável, com o agente como primeiro filtro antes da sua aprovação."
- **Esperado:** `deploy-qa` roda `bundle deploy -t qa`.

### Passo 8 — Aprovar gate prod (~1 min)

- **Fazer:** aprovar gate de prod da mesma forma.
- **Dizer:** "E aqui prod. Safe para rodar ao vivo porque usamos schema-per-env num catálogo sandbox. A recomendação de futuro é catalog-per-env real — mesmo padrão, isolamento mais forte."
- **Esperado:** `deploy-prod` → cascade completo verde.

---

## Passo a passo — Cenário 2: gate-blocker (Gate 2 bloqueia)

**Duração estimada: 10–15 min**

### Passo 1 — Abrir o PR gate-blocker (~2 min)

- **Fazer:** abrir o PR `demo/ml-gate-blocker` no browser.
- **Dizer:** "Este PR parece impecável para o Gate 1 — nenhuma violação de política. A mudança remove algumas features do config e corta `n_estimators` para 5. Vamos ver o que acontece depois do merge."
- **Esperado:** Gate 1 **verde** (sem BLOCKERs), PR passa no review.

### Passo 2 — Merge → Gate 2 bloqueia (~5–8 min)

- **Fazer:** aprovar e fazer merge. Aguardar o `model_training_job` rodar. Mostrar o log da task `promotion_gate` quando ela falhar.
- **Dizer:** "Gate 1 passou. O modelo foi treinado e registrado como `@challenger`. Mas o Gate 2 comparou as métricas do challenger com o champion e detectou degradação — MAE piorou além do threshold configurado. Decisão: BLOCK. O `@champion` não se move. O job falha com o raciocínio completo visível no log e no MLflow."
- **Mostrar:** no MLflow UI, a trace do gate com o reasoning do LLM e os findings citados (ML-03).
- **Dizer:** "Isso demonstra por que o Gate 2 existe: mudanças que passam pela política de código mas degradam o modelo silenciosamente são exatamente o que o Gate 2 captura. O humano ainda precisaria aprovar — mas o primeiro filtro fez o trabalho pesado."
- **Esperado:** job falha na task `promotion_gate`; `@champion` continua em v1; trace MLflow visível.

---

## Extras (se sobrar tempo)

### A. MLflow trace do Gate 2

- **Fazer:** abrir o MLflow UI → Experiments → mostrar a trace da promotion gate com o reasoning e os findings citados do LLM.
- **Dizer:** "Cada decisão do Gate 2 fica rastreada no MLflow — inputs, saída estruturada, justificativa. Não é 'confie no modelo', é auditável."

### B. Agent-as-code recursion

- **Fazer:** abrir o job `modelops_agent_lifecycle` na Jobs UI do workspace.
- **Dizer:** "O titular: o próprio revisor se deploy com o mesmo pipeline que ele vigia. Está no DABs — build_index → register_model → deploy_endpoint → run_eval. Asset governado do Unity Catalog: versionado, avaliado, com linhagem."

### C. AI Gateway / inference table

- **Fazer:** mostrar a inference table `...modelops_reviewer_payload` ou rodar `python modelops_reviewer/gateway/cost_report.py`.
- **Dizer:** "Cada revisão fica registrada via AI Gateway — reviews/dia, latência, custo estimado por PR. Para o full governance suite (rate limits, guardrails PII), mostramos com um endpoint dedicado de FM."

---

## Plano B por ponto de falha

| Falha | Plano B |
|---|---|
| Endpoint `modelops-reviewer` frio / timeout | Gate 1 já é advisory por design — vai postar "unavailable / non-blocking" e o CI sai 0. Narrar como graceful degradation. |
| Runner self-hosted offline | Acordar o runner: SSH no Mac, rodar `./run.sh`. Se não acessível, acionar a gravação de backup. |
| Knowledge Assistant `modelops-handbook-ka` lento | O agente tem fallback para VS direto ou resposta sem citação — narrar que o KA está aquecendo. |
| Gate 2 demora a treinar | Mostrar o MLflow run em tempo real enquanto espera (boa conversa sobre tracking). |
| PR de demo não existe (reset não rodou) | Rodar `bash scripts/reset_demo.sh --open-prs` imediatamente. |
| GitHub Actions travado / runner morreu no meio | Re-queue o run no UI do Actions. O deploy é idempotente. |
| Aprovação de gate travada | `concurrency: cancel-in-progress: false` — o run aprovado não morre. Re-aprovar no UI. |
| Qualquer falha crítica ao vivo | Acionar a gravação de backup pré-gravada. Narrar o que seria visto na tela enquanto passa o vídeo. |

---

## Timings esperados por etapa

| Etapa | Tempo estimado |
|---|---|
| Setup / checklist | antes da reunião |
| Enquadramento do problema | 2 min |
| Abrir PR review-blocker | 1 min |
| Gate 1 roda e posta findings | 1–2 min (webhook → runner → endpoint) |
| `/modelops-fix` → PR de fix aberto | 2–3 min |
| Merge + deploy-dev | 2–3 min |
| model_training_job (Gate 2) | 3–5 min |
| Gates qa/prod | 1 min (aprovação humana) |
| Abrir PR gate-blocker | 1 min |
| Gate 1 passa, Gate 2 bloqueia | 5–8 min |
| MLflow trace / extras | 5 min |
| **Total** | **~45–55 min** |

---

## Referências rápidas

```bash
# Health check dos endpoints
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks serving-endpoints get modelops-reviewer
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks serving-endpoints get ka-5f315d3c-endpoint

# Estado do modelo UC
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks models get-version \
  malcoln_aws_stable_catalog.agentic2_mlops_dev.demand_forecaster

# Reset completo
bash scripts/reset_demo.sh

# Validar bundle
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t dev
```

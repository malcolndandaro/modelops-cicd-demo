# ModelOps CI/CD Demo — Two AI Gates for ML Model Promotion on Databricks

End-to-end CI/CD demo for ML assets on Databricks. The headline: **two AI validation
gates** protect every model promotion — one at PR time, one before merge.

## The idea in one line

> On every PR, deterministic linters catch **syntax** (Ruff, sqlfluff, `bundle validate`)
> and **Gate 1** (a KA-grounded AI reviewer) catches **semantic/policy** problems no
> tool can detect (e.g., a dev config referencing the prod schema). Also pre-merge,
> **Gate 2** (an LLM-driven promotion gate) trains the change, compares the challenger
> model's metrics to the current champion, and blocks the merge if quality degrades. Only
> BLOCKER findings block; humans still approve each environment promotion.

## Table of contents

- [The two gates](#the-two-gates)
- [The pipeline](#the-pipeline)
- [Demo scenarios](#demo-scenarios)
- [🗺️ Code map — where each thing is defined](#️-code-map--where-each-thing-is-defined)
- [Repo structure](#repo-structure)
- [How to run](#how-to-run)
- [Conventions & notes](#conventions--notes)

## The two gates

### Gate 1 — the ModelOps Reviewer (semantic/policy)

An **MLflow `ResponsesAgent`** deployed on **Databricks Model Serving**
(endpoint `modelops-reviewer`), grounded on the **ModelOps Handbook** (ML + platform
standards) via a **Knowledge Assistant** (`modelops-handbook-ka`), powered by
`databricks-glm-5-2`.

- **Review mode** (auto on every PR): posts cited findings + a **`ModelOps Reviewer`
  Check Run** that gates the merge by severity.
- **Fix mode** (`/modelops-fix`, human-triggered): a **GitHub App** bot opens a **new PR
  against the original PR's head branch** with the fix applied, which re-triggers the
  review (self-correcting loop).
- **Agent-as-code**: the reviewer is built, deployed, and evaluated by the **same
  pipeline it guards** (a DABs job: index → register → deploy → eval).

### Gate 2 — the Promotion Gate (model quality)

A `model_training_job` runs four tasks:

1. **train** — trains a `demand_forecaster` (RandomForestRegressor, scikit-learn),
   logs the run to MLflow 3.
2. **register** — registers the model to Unity Catalog as
   `<catalog>.<schema>.demand_forecaster`; the new version receives the `@challenger` alias.
3. **promotion_gate** — an LLM (GLM-5-2) compares challenger vs champion metrics +
   the training-config diff against the ML handbook rules; returns `APPROVE` or `BLOCK`
   with cited findings and justification (MLflow-traced).
4. **promote** — if `APPROVE`, moves `@champion` to the challenger; on `BLOCK` the job
   fails with the gate's reasoning and `promote` is skipped.

The gate runs **pre-merge** as a required check: a BLOCK stops the merge, so a degraded
model's config never lands on `main`. Post-merge, each environment trains and validates
its **own** model in its **own** schema behind the same gate.

## The pipeline (GitHub Actions + Databricks Asset Bundles)

```
PR  →  pr-checks (Ruff + sqlfluff + bundle validate + integration + Gate 2 pre-merge)
    +  modelops-review (Gate 1 Check Run)  →  /modelops-fix (bot opens fix PR)
    →  human approval + merge to main
    →  deploy-dev  →  [gate qa] deploy-qa + train/Gate 2  →  [gate prod] deploy-prod + train/Gate 2
```

| Workflow (`.github/workflows/`) | What it does |
|---|---|
| `pr-checks.yml` | Deterministic linters + `bundle validate` (dev/qa/prd) + ephemeral per-PR deploy, integration tests, and **Gate 2 pre-merge** (train → register → gate → promote) |
| `modelops-review.yml` | Gate 1: agent reviews the diff, posts a severity-gated Check Run |
| `modelops-fix.yml` | `/modelops-fix` → GitHub App bot opens a fix PR against the original PR's branch |
| `deploy.yml` | Post-merge: deploy dev → **gate qa** (deploy + train/Gate 2) → **gate prod** (deploy + train/Gate 2) |

## Demo scenarios

Two bad-PR scenarios under `bad-pr/`, each caught by a *different* gate:

| Scenario | What it does | Which gate catches it | Rule |
|---|---|---|---|
| `bad-pr/ml-review-blocker/` | A dev-context job hardcodes a prod schema reference; touches no model config | **Gate 1 BLOCKS** | ENV-01 |
| `bad-pr/ml-gate-blocker/` | Clean change that passes review but degrades the model | Gate 1 passes, **Gate 2 BLOCKS** | ML-03 |

## 🗺️ Code map — where each thing is defined

Quick navigation for "where is X defined?" Anchors are `file:line` (relative to repo root);
if the code moves, the symbols are still findable by name with `grep -n`.

### The model (`demand_forecaster`)

| Where is... | File:line |
|---|---|
| Model config (hyperparameters, features, threshold) | `src/ml/config.yml` — `n_estimators` `:11`, `max_depth` `:12`, `features` `:18`, `max_acceptable_mae` `:32` |
| Training (RandomForest, MLflow autolog) | `src/ml/train.py:146` (`train`), `:181` (`RandomForestRegressor`) |
| Register to UC (new version + `@challenger`) | `src/ml/register.py:78` (`register_and_alias`), FQN `:51` |
| Catalog/schema resolution | `src/ml/register.py:49` + `src/ml/_config.py:27` (`resolve_catalog_schema`) |
| Alias contract (`@champion`/`@challenger`, UC aliases only) | `src/ml/register.py:8`, `src/ml/promote.py:53` |
| Metric-regression test (MAE ≤ threshold) | `tests/test_demand_forecaster.py` |

> **No wheel:** jobs run source directly on serverless via `spark_python_task` →
> `python_file: ...` (not `python_wheel_task`). See `resources/jobs/*.job.yml`.

### The agent (Gate 1 reviewer)

| Where is... | File:line |
|---|---|
| Agent definition (`ResponsesAgent`) | `modelops_reviewer/agent/agent.py:137` (`ModelopsReviewer`), `:158` (`set_model`) |
| LLM call (GLM as CI SP, oauth-m2m) | `agent.py:98` (`_call_llm`), `:120` (oauth-m2m), `:124` (`get_open_ai_client`) |
| Handbook retrieval (Knowledge Assistant) | `agent.py:66` (`_query_ka`), endpoint `:28` (`KA_ENDPOINT`) |
| Register agent to UC (move `@prod`) | `modelops_reviewer/agent/log_model.py:51`, alias `:77`, FQN `:17` |
| Deploy to serving endpoint (inject SP creds) | `modelops_reviewer/agent/deploy_agent.py:32`, `:39` (`MODELOPS_SP_CLIENT_ID`) |
| All decision logic (pure, tested core) | `modelops_reviewer/agent/review_core.py` |
| Handbook rules | `modelops_handbook/` — ENV-01 `catalog-per-env.md:6`, ML-01 `ml-model-lifecycle.md:8` |

### GitHub Actions — workflows and gates

| Where is... | File:line |
|---|---|
| Gate 1 trigger (every PR) | `.github/workflows/modelops-review.yml:6` (`pull_request`), runs `:50` |
| `/modelops-fix` (comment-triggered) | `.github/workflows/modelops-fix.yml:7` (`issue_comment`), App token `:35`, runs `:86` |
| Deterministic gates | `.github/workflows/pr-checks.yml` — ruff `:16`, sqlfluff `:32`, bundle validate `:55` |
| Gate 2 pre-merge (blocks the merge) | `.github/workflows/pr-checks.yml:85` (`integration`), runs `:113` |
| Post-merge deploy (dev → qa → prod) | `.github/workflows/deploy.yml` — dev `:33`, qa `:52`, prod `:74` |
| Deploy gate (required human reviewer) | `deploy.yml:57` (`environment: qa`), `:79` (`environment: prod`) |

### Where the BLOCK happens

| Gate | How it blocks | File:line |
|---|---|---|
| Gate 1 | Any `BLOCKER` finding → Check Run `failure`. CI always exits 0; the Check Run is the gate. | `review_core.py:263` (`decide_gate`), `:291` (`to_check_run`); shell `ci/review_pr.py:52` (`post_check_run`), `:140` |
| Gate 2 | `BLOCK` → `promotion_gate` task **raises** → job fails → `promote` is skipped → pre-merge check red. | `src/ml/promotion_gate.py:350`; core `src/ml/promotion_core.py:252` (`parse_decision`), `:308` (bootstrap) |
| Task dependency | `promote` `depends_on` `promotion_gate`; on failure Jobs skips `promote`. | `resources/jobs/model_training_job.job.yml:47` |
| Fix authorization | Refuses forks, requires write/maintain/admin, refuses protected branches, confines to changed files. | `review_core.py:365` (`is_authorized`), shell `ci/fix_pr.py:200` |

### DABs / bundle (deploy config)

| Where is... | File:line |
|---|---|
| Bundle + targets (dev/qa/prd) | `databricks.yml:34` (`targets`) |
| Catalog/schema per env (the per-env boundary) | `databricks.yml:45` (dev), `:53` (qa→staging), `:64` (prd→prod) |
| `run_as` = CI SP (why qa/prd only run in CI) | `databricks.yml:15` (`sp_client_id`), `:54`/`:65` |
| Served agent version (config-only redeploy) | `databricks.yml:20` (`agent_model_version`, default `@prod`) |
| Training job (Gate 2) | `resources/jobs/model_training_job.job.yml` — tasks `:25`/`:31`/`:39`/`:47` |
| Agent lifecycle job (build→register→deploy→eval) | `resources/jobs/modelops_agent.job.yml` — tasks `:16`/`:21`/`:28`/`:41` |

## Repo structure

```
modelops_reviewer/      ← Gate 1: the reviewer agent
  agent/               pure functional core (review_core.py) + ResponsesAgent + log/deploy
  ci/                  CI shells: review_pr.py (comment + Check Run), fix_pr.py (fix PR)
  index/               builds the handbook table + Vector Search index
  eval/                mlflow.genai.evaluate harness (regression gate) + fixtures
  gateway/             AI Gateway config and cost report
  tests/               40 unit tests over the pure core
modelops_handbook/      ← ML + platform standards (Knowledge Base for both gates)
src/
  ml/                  Gate 2: train.py, register.py, promotion_gate.py, promote.py, config.yml
  retail/              retail pipeline transforms (pure functions, transform-pattern)
  jobs/                retail pricing jobs (supporting DE pipeline)
  daily_route_profitability.py   retail job entrypoint
data/seed_retail.py    synthetic seed generator for fact_sales / dim_store source tables
tests/                 unit tests (promotion_core, demand_forecaster) + serverless integration
bad-pr/                the two demo scenarios: ml-review-blocker/, ml-gate-blocker/
resources/jobs/        DABs job YAML definitions
scripts/reset_demo.sh  idempotent demo reset (PRs, UC model, ownership, grants, seeds)
sql/                   SQL assets
docs/                  Azure DevOps translation guide (ado-translation.md + azure-pipelines-*.yml)
databricks.yml         DABs bundle modelops-cicd-demo; targets dev/qa/prd
```

## How to run

```bash
# Linters (what pr-checks runs)
ruff check src/ modelops_reviewer/
ruff format --check src/
sqlfluff lint sql/

# Bundle
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t dev
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle deploy -t dev

# Unit tests (no workspace needed)
pytest modelops_reviewer/tests/ tests/test_promotion_core.py tests/test_demand_forecaster.py -v

# Seed source tables (Databricks Connect serverless)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws python data/seed_retail.py

# Deploy Gate 1 agent end-to-end (index → register → deploy → eval)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle run modelops_agent_lifecycle -t dev

# Reset demo state (PRs, branches, UC model, ownership, grants, seeds)
bash scripts/reset_demo.sh
```

More detail: **`CLAUDE.md`** (full architecture, repo map, conventions, hard-won operational
insights) and **`docs/ado-translation.md`** (Azure DevOps parity guide).

## Conventions & notes

- Repo **public** — no secrets or sensitive identifiers committed. Secrets live in GitHub
  Actions secrets; non-secret config in repo variables.
- CI authenticates to Databricks via **OAuth M2M** service principal. Every Databricks-
  touching job runs on the **self-hosted runner** (VPN-only workspace).
- Gate 1 reviewer is **advisory-never-block**: CI always exits 0; the Check Run conclusion
  is the gate. A cold endpoint degrades to an advisory comment.
- Gate 2 uses **Unity Catalog aliases** (`@champion`/`@challenger`) — no deprecated
  workspace-registry stages.
- **Env = schema** in this demo (single catalog, schemas `*_dev` / `*_staging` / `*_prod`).
  Future-state recommendation is catalog-per-env isolation.
- **Functional-core / imperative-shell**: all decision logic is pure and unit-tested
  (`review_core.py`, `promotion_core.py`); side effects live in thin shells.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).

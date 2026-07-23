# ModelOps CI/CD Demo — Two AI Gates for ML Model Promotion on Databricks

End-to-end CI/CD demo for ML assets on Databricks. The headline: **two AI validation
gates** protect every model promotion — one at PR time, one at deployment time.

## The idea in one line

> On every PR, deterministic linters catch **syntax** (Ruff, sqlfluff, `bundle validate`)
> and **Gate 1** (a KA-grounded AI reviewer) catches **semantic/policy** problems no
> tool can detect (e.g., a dev config referencing the prod schema). After merge,
> **Gate 2** (an LLM-driven promotion gate) compares the challenger model's metrics to
> the current champion and blocks promotion if quality degrades. Only BLOCKER findings
> block; humans still approve each environment promotion.

## What is the ModelOps Reviewer (Gate 1)

An **MLflow `ResponsesAgent`** deployed on **Databricks Model Serving**
(endpoint `modelops-reviewer`), grounded on the **ModelOps Handbook** (ML + platform
standards) via a **Knowledge Assistant** (`modelops-handbook-ka`), powered by
`databricks-glm-5-2`.

- **Review mode** (auto on every PR): posts cited English findings + a
  **`ModelOps Reviewer` Check Run** that gates the merge by severity.
- **Fix mode** (`/modelops-fix`, human-triggered): the bot opens a **new PR against
  the original PR's head branch** with the fix applied, which re-triggers the review
  (self-correcting loop).
- **Agent-as-code**: the reviewer is built, deployed, and evaluated by the **same
  pipeline it guards** (a DABs job: index → register → deploy → eval).

## What is the Promotion Gate (Gate 2)

After merge, a `model_training_job` runs:
1. **train** — trains a `demand_forecaster` (RandomForestRegressor, scikit-learn),
   logs the run to MLflow 3.
2. **register** — registers the model to Unity Catalog as
   `<catalog>.<schema>.demand_forecaster`; new version receives the `@challenger` alias.
3. **promotion_gate** — an LLM (GLM-5-2) compares challenger vs champion metrics +
   the training-config diff against the ML handbook rules; returns `APPROVE` or `BLOCK`
   with cited findings and justification (MLflow-traced).
4. **promote** — if `APPROVE`, moves `@champion` to the challenger; otherwise the job
   fails with the gate's reasoning.

## The pipeline (GitHub Actions + Databricks Asset Bundles)

```
PR  →  pr-checks (Ruff + sqlfluff + bundle validate)  +  modelops-review (Gate 1 Check Run)
    →  /modelops-fix (bot opens fix PR)  →  human approval + merge to main
    →  deploy-dev + Gate 2 (train → register → gate → promote)
    →  [gate qa]  →  deploy-qa  →  [gate prod]  →  deploy-prod
```

| Workflow (`.github/workflows/`) | What it does |
|---|---|
| `pr-checks.yml` | Deterministic linters (syntax) + `bundle validate` for dev/qa/prd |
| `modelops-review.yml` | Gate 1: agent reviews diff, posts severity-gated Check Run |
| `modelops-fix.yml` | `/modelops-fix` → bot opens a fix PR against the original PR's branch |
| `deploy.yml` | Post-merge: dev deploy + Gate 2 → **gate qa** → **gate prod** |

## Demo scenarios

Two bad-PR scenarios under `bad-pr/`:

| Scenario | What it does | Which gate catches it | Rule |
|---|---|---|---|
| `bad-pr/ml-review-blocker/` | Hyperparameter change without updating regression test + cross-env config reference | **Gate 1 BLOCKS** | ML-01, ENV-01 |
| `bad-pr/ml-gate-blocker/` | Clean change that passes review but degrades the model | Gate 1 passes, **Gate 2 BLOCKS** | ML-03 |

## Repo structure

```
modelops_reviewer/      ← Gate 1: the reviewer agent
  agent/               pure functional core (review_core.py) + ResponsesAgent + log/deploy
  ci/                  CI shells: review_pr.py (comment + Check Run), fix_pr.py (new fix PR)
  index/               builds handbook table + Vector Search index
  eval/                mlflow.genai.evaluate harness (regression gate)
  gateway/             AI Gateway config and cost report
  tests/               37 unit tests over the pure core
modelops_handbook/      ML + platform standards (the Knowledge Base for Gate 1 + Gate 2)
src/
  ml/                  Gate 2: train.py, register.py, promotion_gate.py, promote.py, config.yml
  retail/              Retail pipeline transforms (pure functions, transform-pattern)
  jobs/                Retail pricing jobs (supporting DE pipeline)
  daily_route_profitability.py   Retail job entrypoint
data/seed_retail.py    Synthetic seed generator for fact_sales / dim_store source tables
tests/                 Unit tests (promotion_core, demand_forecaster, reviewer core) + integration
bad-pr/                Anti-examples: ml-review-blocker/, ml-gate-blocker/, legacy linter examples
resources/jobs/        DABs job YAML definitions
sql/                   SQL assets
docs/                  Azure DevOps translation guide (ado-translation.md + azure-pipelines-*.yml)
databricks.yml         DABs bundle modelops-cicd-demo; targets dev/qa/prd
```

## How to run

```bash
# Linters (what pr-checks runs)
ruff check src/ modelops_reviewer/
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

# Reset demo state (PRs, branches, UC model aliases)
bash scripts/reset_demo.sh
```

## Documentation

- **`CLAUDE.md`** — full architecture, repo map, conventions, live assets.
- **`DEMO.md`** — step-by-step runbook in PT-BR (presenter's language).
- **`docs/ado-translation.md`** — Azure DevOps parity guide.

## Notes

- Repo **public** — no secrets or workspace identifiers committed. Secrets live in
  GitHub Actions secrets; non-secret config in repo variables.
- CI authenticates to Databricks via **OAuth M2M** service principal. Every Databricks-
  touching job runs on the **self-hosted runner** (VPN-only workspace).
- Gate 1 reviewer is **advisory-never-block**: CI always exits 0; the Check Run
  conclusion is the gate. A cold endpoint degrades to an advisory comment.
- Gate 2 uses **Unity Catalog aliases** (`@champion`/`@challenger`) — no deprecated
  workspace-registry stages.
- **Env = schema** in this demo (single catalog `malcoln_aws_stable_catalog`, schemas
  `agentic2_mlops_dev` / `agentic2_mlops_staging` / `agentic2_mlops_prod`). Future-state
  recommendation is catalog-per-env isolation.

# CLAUDE.md — ModelOps CI/CD Demo

> **Current deployment:** workspace `https://dbc-967959c2-d585.cloud.databricks.com` ·
> catalog `malcoln_aws_stable_catalog` · CLI profile `agentic-mlops-cicd-aws` (M2M OAuth).
> GitHub repo: `malcolndandaro/modelops-cicd-demo` (public — keep secrets out).
>
> Orientation for any engineer or agent opening this repo. Read this first, then `DEMO.md`.

## What this repo is

**ModelOps CI/CD Demo** — an end-to-end CI/CD pipeline for ML assets on Databricks,
with **two AI validation gates**:

- **Gate 1 — PR Reviewer (semantic/policy gate):** a custom MLflow `ResponsesAgent` on
  Databricks Model Serving, grounded on the **ModelOps Handbook** via a Knowledge
  Assistant (`modelops-handbook-ka`), powered by `databricks-glm-5-2`. On every PR it
  reads the diff, retrieves the relevant standards, and posts cited, severity-tagged
  findings as a GitHub Check Run. It catches what deterministic linters cannot — e.g.
  a dev config referencing the prod schema (`agentic2_mlops_prod` from a dev context).
  `/modelops-fix` opens a **new fix PR against the original PR's head branch**.

- **Gate 2 — Promotion Gate (model-quality gate):** after merge, a training job trains a
  `demand_forecaster` challenger, registers it to Unity Catalog, then an LLM-driven gate
  compares challenger vs champion metrics + the training config diff against ML handbook
  rules. Returns `APPROVE` (moves `@champion` alias) or `BLOCK` (fails the job with
  reasoning, MLflow-traced).

The **retail pipeline** (`src/retail/`, `src/daily_route_profitability.py`) is a
supporting DE pipeline that seeds the demo data and exercises the transform-pattern and
DABs deployment — it is NOT the demo protagonist. The ML pipeline under `src/ml/` is.

## Architecture

### Gate 1 — PR Reviewer (`modelops_reviewer/`)

- **MLflow `ResponsesAgent` on Model Serving.** Registered to UC as
  `malcoln_aws_stable_catalog.agentic2_mlops_dev.modelops_reviewer` (alias `@prod`),
  served at endpoint `modelops-reviewer` (task `agent/v1/responses`).
- **KA-grounded.** Rules come from the ModelOps Handbook, retrieved via the Knowledge
  Assistant. Its Agent Bricks **display name** is `modelops-handbook-ka`, but the KA's
  **serving endpoint** is auto-named `ka-5f315d3c-endpoint` — that's what the agent
  invokes (overridable via the `KA_ENDPOINT` env var; the reviewer/fix shells default to
  it). The KA speaks the Responses API (`input[]` / `output[].content[].text`), not
  chat-completions. Requires the workspace NOT enrolled in the Serverless Access Controls
  Preview (Agent Bricks KA is blocked while that preview is on).
- **LLM:** `databricks-glm-5-2`, `temperature=0.0`. **FM auth:** this account has the
  Foundation Model UC permissions feature enabled, so the calling identity needs `EXECUTE`
  on `system.ai.databricks-glm-5-2` (+ `USE_CATALOG on system`, `USE_SCHEMA on system.ai`).
  The deployed agent's down-scoped OBO token does NOT carry these, so `_call_llm`
  authenticates as the **CI SP** (which holds the grant) via
  `WorkspaceClient(..., auth_type="oauth-m2m").serving_endpoints.get_open_ai_client()`,
  with the SP creds injected as served-entity env vars `MODELOPS_SP_CLIENT_ID` /
  `MODELOPS_SP_CLIENT_SECRET`. `auth_type="oauth-m2m"` is REQUIRED — inside serving the
  ambient OBO token collides with the SP creds otherwise.
- **Two modes, one agent.** *Review mode* (auto on every PR) posts cited findings + a
  Check Run. *Fix mode* (`/modelops-fix`) opens a new `modelops-fix/...` branch with the
  rewrite applied, opens a PR against the original PR's head branch, and comments the
  link on the original PR.
- **Severity gate:** BLOCKER findings → Check Run `failure`; SUGGESTION/STYLE → advisory
  only. CI always `sys.exit(0)` — the Check Run is the gate, not the job exit code. A
  cold endpoint yields an advisory "unavailable / non-blocking" comment.

### Gate 2 — Promotion Gate (`src/ml/`)

- **Training job (`model_training_job`):** four tasks in DABs:
  `train` → `register` → `promotion_gate` → `promote`.
- **Pure core (`promotion_core.py`):** prompt construction (metrics + config diff),
  defensive JSON parsing, bootstrap rule (no champion → APPROVE), metric comparison.
  No LLM call, no MlflowClient in the tested path.
- **Gate outcome:** `APPROVE` → promote task runs and moves `@champion`; `BLOCK` → job
  fails with full reasoning in log.
- **UC aliases only.** `@champion` / `@challenger` — no workspace-registry stages.
- **MLflow tracing:** gate steps are instrumented with spans visible in the MLflow UI.

### The pipeline (GitHub Actions + DABs)

```
PR → pr-checks (Ruff + sqlfluff + bundle validate)  +  modelops-review (Gate 1 Check Run)
   → /modelops-fix (bot opens fix PR)  → human approval + merge to main
   → deploy-dev + model_training_job (Gate 2)  → [gate qa]  → deploy-qa  → [gate prod]  → deploy-prod
```

## Repo map

| Path | Role |
|---|---|
| `modelops_reviewer/agent/review_core.py` | Pure functional core for Gate 1 (444+ lines, no I/O). All decisions: context builder, prompt builders, finding parser, severity gate, check-run mapper, authz, fix-file selection, content validation, eval scorers. |
| `modelops_reviewer/agent/agent.py` | MLflow `ResponsesAgent` shell — KA retrieval + FM call. |
| `modelops_reviewer/agent/log_model.py` | Register agent to UC, move `@prod` alias. |
| `modelops_reviewer/agent/deploy_agent.py` | `databricks.agents.deploy(...)` to endpoint `modelops-reviewer`. |
| `modelops_reviewer/ci/review_pr.py` | CI review shell: invoke endpoint → cited comment + Check Run. Always `sys.exit(0)`. |
| `modelops_reviewer/ci/fix_pr.py` | CI fix shell: authz → re-review → FM fix → validate → bot opens new fix PR. |
| `modelops_reviewer/index/` | `build_handbook_index.py` (parse handbook → table + VS index), `verify_retrieval.py`. |
| `modelops_reviewer/eval/` | `run_eval.py` (mlflow.genai.evaluate, 100% regression gate), `scorers.py`, `fixtures.py`. |
| `modelops_reviewer/gateway/` | AI Gateway config and cost report. |
| `modelops_reviewer/tests/test_review_core.py` | 40 unit tests over the pure core. |
| `modelops_handbook/` | 8 markdown files (README + 7 topics): ENV, TP, SQL, SEC, NM, DABs, and **ML lifecycle (ML-01..ML-05)**. Uploaded to UC volume `handbook_volume`, indexed by the KA. |
| `src/ml/` | Gate 2: `train.py`, `register.py`, `promotion_core.py`, `promotion_gate.py`, `promote.py`, `config.yml`. |
| `src/retail/transforms.py` | Pure retail pipeline transforms (vendored, transform-pattern). |
| `src/daily_route_profitability.py` | Retail job entrypoint notebook. |
| `src/jobs/` | Retail pricing jobs (supporting DE pipeline, demo of transform-pattern). |
| `data/seed_retail.py` | Synthetic seed for `fact_sales` / `dim_store` source tables. |
| `tests/test_promotion_core.py` | Unit tests for Gate 2 pure core. |
| `tests/test_demand_forecaster.py` | **Metric-regression gate** — asserts model MAE ≤ `max_acceptable_mae` in config.yml. Demo prop: bad-PR #1 "forgets" to update it (ML-01 BLOCKER). |
| `tests/conftest.py` | Serverless integration test fixtures. |
| `tests/test_pipeline_serverless.py` | Serverless integration tests for the retail pipeline. |
| `bad-pr/ml-review-blocker/` | Bad PR scenario 1: caught by Gate 1 (ML-01, ENV-01). |
| `bad-pr/ml-gate-blocker/` | Bad PR scenario 2: passes Gate 1, blocked by Gate 2 (ML-03). |
| `bad-pr/` | Legacy linter anti-examples (bad_python.py, bad_sql.sql, broken_bundle). |
| `resources/jobs/` | DABs job YAML definitions. |
| `sql/` | SQL assets. |
| `scripts/reset_demo.sh` | Idempotent demo reset: PRs, branches, UC model aliases, endpoints. |
| `.github/workflows/` | `pr-checks.yml`, `modelops-review.yml`, `modelops-fix.yml`, `deploy.yml`. |
| `databricks.yml` | DABs bundle `modelops-cicd-demo`; targets `dev`/`qa`/`prd`; var `agent_model_version`. |
| `docs/ado-translation.md` (+ 4 `azure-pipelines-*.yml`) | GitHub Actions → Azure DevOps parity guide. |

## How to deploy / operate

```bash
# Validate the bundle for every target (what CI runs)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t dev
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t qa
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t prd

# Deploy
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle deploy -t dev

# Run unit tests (no workspace, no network)
pytest modelops_reviewer/tests/ tests/test_promotion_core.py tests/test_demand_forecaster.py -q

# Build/ship the Gate 1 agent end-to-end (index → register → deploy → eval)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle run modelops_agent_lifecycle -t dev

# Register Gate 1 model manually (moves the @prod alias)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws python modelops_reviewer/agent/log_model.py

# Seed source tables (Databricks Connect serverless)
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws python data/seed_retail.py

# Reset demo state
bash scripts/reset_demo.sh
```

**Config-only Gate 1 redeploy:** bump `agent_model_version` in `databricks.yml` and run
the `deploy_endpoint` task. First deploy ~15 min; a version swap is a fast in-place
update. Never set `agent_model_version` to `""` (empty string panics the TF provider).

## Conventions & hard rules

- **Functional-core / imperative-shell.** All decision logic is pure and unit-tested
  (Gate 1: `review_core.py`; Gate 2: `promotion_core.py`). Every side effect lives in
  thin shells. Changing behavior = change the core and a test; keep shells dumb.
- **Severity-gated, never-block review.** Only BLOCKER findings drive `failure` Check
  Run. CI scripts always `sys.exit(0)`. A cold endpoint degrades gracefully.
- **Changed-file confinement + fork refusal in fix mode.** Fix mode refuses fork PRs,
  requires write/maintain/admin on a non-protected branch, confines fixes to PR's changed
  files, and aborts if any rewritten file fails to parse.
- **Schema-per-env (demo).** One catalog `malcoln_aws_stable_catalog`, schemas
  `agentic2_mlops_dev` / `agentic2_mlops_staging` / `agentic2_mlops_prod`. Hero ENV-01
  violation: a dev config reading from `agentic2_mlops_prod`.
- **UC aliases only.** `@champion` / `@challenger` for Gate 2; no workspace-registry
  stages. Comment in code explicitly calls this out for the "stage transitions" question.
- **M2M auth + self-hosted runner.** CI authenticates via OAuth M2M SP (`sp-modelops-ci`).
  All Databricks-touching jobs run on the self-hosted runner (VPN-only workspace) at
  `/Users/malcoln.dandaro/Documents/Work/Projects/actions-runner`.
- **Fix-bot = GitHub App (not a PAT).** `/modelops-fix` runs as the GitHub App: the
  workflow mints a short-lived installation token via `actions/create-github-app-token`
  (App id in repo var `MODELOPS_BOT_APP_ID`, private key in secret
  `MODELOPS_BOT_APP_PRIVATE_KEY`). The App push (distinct from `GITHUB_TOKEN`) re-triggers
  review + checks. GitHub Environments `qa`/`prod` gate the deploy with a required reviewer.
- **Secret hygiene.** PUBLIC repo. GitHub Actions secrets: `DATABRICKS_CLIENT_SECRET`,
  `MODELOPS_BOT_APP_PRIVATE_KEY`. Repo variables: `DATABRICKS_HOST`,
  `DATABRICKS_SP_CLIENT_ID`, `MODELOPS_BOT_APP_ID`.
- **Output language.** Code identifiers in English; handbook and agent output in English
  (rebranded from the original Spanish demo). PT-BR only in `DEMO.md` (presenter's narration).

## Live assets (verified 2026-07-23 — both gates tested live)

- **Serving endpoint `modelops-reviewer`** — `READY`, UC model v4 `@prod`, FM
  `databricks-glm-5-2`. Smoke-tested: hero diff → BLOCKER ENV-01 + SUGGESTION ENV-02,
  handbook-cited. Serving identity authenticates to the FM as the CI SP (see FM auth above).
- **Knowledge Assistant** — display `modelops-handbook-ka`, serving endpoint
  `ka-5f315d3c-endpoint` (`READY`), grounded on `handbook_volume`. Verified: ENV-01 query
  returns the rule text + a `url_citation`.
- **UC model** `...agentic2_mlops_dev.demand_forecaster` — `@champion` → v1, no
  `@challenger` (clean reset baseline). Bootstrap train→register→gate→promote ran green.
- **Seed tables** `...agentic2_mlops_dev.fact_sales` + `dim_store`.
- **CI SP grants:** `sp-modelops-ci` has `USE_CATALOG` + schema grants on all three schemas,
  plus `EXECUTE` on `system.ai.databricks-glm-5-2`. OAuth M2M auth verified.
- **GitHub:** repo public; secrets/vars set; Environments `qa`/`prod` with required reviewer;
  fix-bot GitHub App installed (contents/PR/issues write).

## Pointers

- `DEMO.md` — live demo runbook in PT-BR (step-by-step, timings, plan B per failure).
- `docs/ado-translation.md` — GitHub Actions → Azure DevOps parity.
- `scripts/reset_demo.sh` — idempotent reset for all demo state.

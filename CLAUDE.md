# CLAUDE.md — ModelOps CI/CD Demo

> **Current deployment:** workspace `https://dbc-967959c2-d585.cloud.databricks.com` ·
> catalog `malcoln_aws_stable_catalog` · CLI profile `agentic-mlops-cicd-aws` (M2M OAuth).
> GitHub repo: `malcolndandaro/modelops-cicd-demo` (public — keep secrets out).
>
> Orientation for any engineer or agent opening this repo. Read this first, then `DEMO.md`.

> **STATUS (verified end-to-end 2026-07-23): DEMO-READY. ✅**
> Both AI gates, the deploy cascade, the reset loop, and `/modelops-fix` were all run
> **live** on this workspace + the self-hosted runner (not just locally):
> - **Gate 1** — on the review-blocker PR: Ruff / sqlfluff / bundle-validate / integration
>   tests all GREEN; only the `ModelOps Reviewer` Check Run is RED, with handbook-cited
>   **ENV-01 + ML-01 BLOCKERs**.
> - **`/modelops-fix`** — the GitHub App bot opens a fix PR against the PR branch and
>   correctly rewrites the ENV-01 line to `${var.catalog}.${var.schema}.gold_pricing`.
> - **Gate 2** — full `train → register → promotion_gate → promote` green in CI as the SP;
>   full deploy cascade `dev → qa → prod` green (both env gates approved).
> - **Reset** — `reset_demo.sh --open-prs` is idempotent; leaves exactly 2 demo PRs and a
>   clean model baseline: **dev** `demand_forecaster` v1 `@champion` / no `@challenger`,
>   **staging + prod wiped** (each bootstraps fresh on the post-merge deploy). Seeds (all 3
>   schemas), experiment grants, and model ownership (→ CI SP, all 3 schemas) self-healed.
> The **"Hard-won operational insights"** section below is the single most important read —
> ~20 real failures had to be fixed to get here, almost all invisible until the code ran as
> the **CI service principal** on the **serverless** job / **self-hosted** runner.
>
> **Left for the human:** rotate the GitHub App client secret if it was ever shared in
> plaintext; before presenting, run `bash scripts/reset_demo.sh --open-prs` for a clean slate.

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
PR (pre-merge, all gate the merge):
   pr-checks:  Ruff + sqlfluff + bundle-validate
             + integration (ephemeral per-PR dev deploy → tests → Gate 2: train → register
               → AI promotion gate → promote;  BLOCK ⇒ check red ⇒ merge blocked)
   modelops-review:  Gate 1 (reviewer) Check Run  →  /modelops-fix (bot opens fix PR)
   → human approval + merge to main
Post-merge (deploy.yml): each env deploys THEN trains + gates its OWN model in its OWN schema:
   deploy-dev  → [gate qa]  → deploy-qa + train/Gate2 (staging schema)
                            → [gate prod]  → deploy-prod + train/Gate2 (prod schema)
```

**Why Gate 2 is pre-merge (as a required check):** if the promotion gate ran only
post-merge, a degraded model's config would already be on `main` before the gate rejected
it (broken main + red deploy). Making it a required pre-merge check means a BLOCK stops the
merge — `main` stays clean. **Post-merge, each environment trains + validates + promotes its
own model** in its own schema behind the same gate (dev pre-merge, then qa in
`agentic2_mlops_staging`, prod in `agentic2_mlops_prod`) — so every env's champion was gated
against that env, not a re-used artifact. First run per env bootstrap-approves (no champion yet).

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
| `bad-pr/ml-review-blocker/` | Bad PR scenario 1: caught by Gate 1 (ENV-01 — pure cross-env ref; touches no model config, so Gate 2 has nothing to flag). |
| `bad-pr/ml-gate-blocker/` | Bad PR scenario 2: passes Gate 1, blocked by Gate 2 (ML-03). |
| `resources/jobs/` | DABs job YAML definitions. |
| `sql/` | SQL assets. |
| `scripts/reset_demo.sh` | Idempotent demo reset: PRs/branches, UC model across all 3 schemas (dev keeps v1, qa/prod wiped), model ownership → CI SP, experiment grants, seed tables, endpoint cleanup. |
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

- **Serving endpoint `modelops-reviewer`** — `READY`, UC model `@prod` (currently v4), FM
  `databricks-glm-5-2`. Live-tested end-to-end: hero diff → cited BLOCKER findings. The
  served agent calls the FM as the CI SP via env-injected creds (see FM-auth insight below).
- **Knowledge Assistant** — display name `modelops-handbook-ka`, serving endpoint
  `ka-5f315d3c-endpoint` (`READY`), grounded on `handbook_volume`. Verified: ENV-01 query
  returns the rule text + a `url_citation`. Speaks the **Responses API** (`input[]`).
- **UC model** `...agentic2_mlops_dev.demand_forecaster` — **`@champion` → v1**, no
  `@challenger` (clean reset baseline). Owned by the **CI SP** (so it can create versions).
  Full train→register→gate→promote verified green in CI as the SP.
- **Seed tables** `fact_sales` + `dim_store` present in **all three** schemas
  (dev/staging/prod). `data/seed_retail.py` regenerates them; `reset_demo.sh` self-heals.
- **CI SP `sp-modelops-ci` grants (all required — see insights):** `USE_CATALOG` + per-schema
  grants on the three schemas; `EXECUTE` on `system.ai.databricks-glm-5-2` (+ `USE_CATALOG`
  on `system`, `USE_SCHEMA` on `system.ai`); `CAN_MANAGE` on the `/ModelOps` experiment +
  folder; **owner** of the `demand_forecaster` model; **`CAN_QUERY`** on BOTH the
  `modelops-reviewer` and `ka-5f315d3c-endpoint` serving endpoints.
- **GitHub:** repo public; secrets `DATABRICKS_CLIENT_SECRET` + `MODELOPS_BOT_APP_PRIVATE_KEY`;
  vars `DATABRICKS_HOST` / `DATABRICKS_SP_CLIENT_ID` / `MODELOPS_BOT_APP_ID`; Environments
  `qa`/`prod` with `malcolndandaro` as required reviewer; fix-bot GitHub App installed
  (contents/PR/issues write); "Allow Actions to create and approve PRs" enabled.

## Hard-won operational insights (what made the demo actually work)

Read this before touching the pipeline. Nearly every item was **invisible in local dev /
`bundle validate` / unit tests** and only surfaced when the code ran as the **CI service
principal** on the **serverless** training job or the **self-hosted** runner. The meta-lesson:
*when a job runs as the SP, every asset it touches must be SP-owned or SP-granted, and
serverless task execution differs from local Python in ways that bite silently.*

### A. Serverless `spark_python_task` execution traps
1. **`__file__` is undefined.** Databricks runs the task via `exec(compile(...))`, so
   module-level `pathlib.Path(__file__)` raises `NameError`. Use a `_repo_root()` helper that
   tries `__file__`, else walks up from `cwd()` for the `databricks.yml` marker.
2. **`sys.exit()` = task FAILURE.** The notebook wrapper reports ANY `SystemExit` (even code
   0/None) as a failed task. So `sys.exit(main())` failed a task that actually succeeded, and
   `sys.exit(0)` on gate APPROVE would wrongly fail the gate. Rule: **call `main()` directly**;
   for the promotion gate, APPROVE = `return`, BLOCK = `raise`.
3. **`/tmp` is read-only and not shared across tasks.** train→register handoff via a `/tmp`
   file crashed; made it best-effort and resolve the run authoritatively via MLflow
   (experiment + `tags.model_name`).
4. **`mlflow.set_experiment("/ModelOps/...")` → NOT_FOUND** if the parent workspace folder
   doesn't exist (it doesn't auto-create). Pre-create with `WorkspaceClient().workspace.mkdirs(parent)`.

### B. Foundation Model auth (this account has the **FM Unity Catalog permissions** feature ON)
5. With that feature enabled, the default schema-wide `EXECUTE` on `system.ai` is revoked;
   each principal needs **`EXECUTE` on the specific model** `system.ai.databricks-glm-5-2`
   (+ `USE_CATALOG on system`, `USE_SCHEMA on system.ai`). Symptom: `403 PERMISSION_DENIED:
   User is missing privileges: USE CATALOG on system`.
6. **The served agent's OBO token is down-scoped** — it does NOT inherit the creator's grants,
   so granting Malcoln wasn't enough. Fix: the deployed agent authenticates to the FM **as the
   CI SP** (which holds the grant), with SP creds injected as served-entity env vars
   (`MODELOPS_SP_CLIENT_ID` / `MODELOPS_SP_CLIENT_SECRET`) by `deploy_agent.py`.
7. **`auth_type="oauth-m2m"` is REQUIRED** when building that SP client inside serving:
   the injected OBO token (`DATABRICKS_TOKEN`) coexists with the SP creds, so without an
   explicit auth_type the SDK errors ("more than one authorization method configured") or
   silently uses the wrong one. `WorkspaceClient(host, client_id, client_secret, auth_type="oauth-m2m")`.
8. **Call the FM via `WorkspaceClient().serving_endpoints.get_open_ai_client()`**, NOT
   `mlflow.deployments.get_deploy_client().predict()` (which re-resolves through the `system`
   catalog and 403s) and NOT `openai.OpenAI(api_key=cfg.token)` (under oauth-m2m `cfg.token`
   is None → "Missing credentials"). `get_open_ai_client()` wraps dynamic OAuth token minting.
9. **The CI SP needs `CAN_QUERY` on BOTH serving endpoints** (`modelops-reviewer` and the KA).
   The review/fix CI jobs run as the SP and invoke them. ⚠️ The reviewer's **advisory-never-block**
   design MASKS a missing grant: the `modelops-review` workflow shows SUCCESS while the reviewer
   actually posted a "not available" fallback. **`modelops-review=success` does NOT prove Gate 1
   works — always read the posted PR comment / Check Run conclusion.**
10. **GLM-5-2 occasionally returns an EMPTY completion.** The gate's `parse_decision` then
    can't parse and defaults to BLOCK — a spurious block. `_call_llm` retries empty responses 3×.
    (The KA also returns an empty envelope via the CLI `serving-endpoints query`; the SDK path
    returns the real `output[].content[].text` — always test via the SDK path the code uses.)

### C. Service-principal ownership / permissions (job runs AS the SP)
11. **Experiment folder:** if `/ModelOps` was first created by a human, the SP can't read it
    (`does not have read permission for node /workspace/<id>`). Grant SP `CAN_MANAGE` on the
    experiment + parent dir. `reset_demo.sh` step 2.5 self-heals this.
12. **Model versions:** the SP couldn't add versions to a human-created (or human-owned)
    model — `register` fails `PERMISSION_DENIED: ... does not have MANAGE on Routine or Model`
    (older API: `does not have CREATE MODEL VERSION`). Fix: **transfer model ownership to the
    SP** (`api patch /api/2.1/unity-catalog/models/<FQN> --json '{"owner":"<sp-app-id>"}'`).
    Owner can create versions AND move aliases (register + promote). ⚠️ This drifts back per
    schema whenever a model is (re)created by a human — bit qa/prod after the per-env split
    (dev was SP-owned, staging/prod were human-owned → qa deploy `register` failed).
    `reset_demo.sh` step 2.7 now self-heals ownership → CI SP for all 3 schemas.
13. **DO NOT churn SP OAuth secrets.** They cap at 5 per SP; minting a new one + deleting old
    ones invalidated the `DATABRICKS_CLIENT_SECRET` in GitHub → `deploy.yml` failed
    `invalid_client`. Keep exactly ONE secret, shared by the GitHub secret AND the reviewer
    endpoint env var. To test the SP identity, trigger the DEPLOYED CI job (uses GitHub's
    secret), don't mint locally.

### D. GitHub Actions / CI
14. **Missing test deps.** The pre-merge integration venv (`pr-checks.yml`) needed
    `mlflow`, `scikit-learn`, `numpy`, `pyyaml` added — `tests/test_demand_forecaster.py`
    imports the training code. Missing → collection ImportError → the whole gate red.
15. **Serverless job env** (`model_training_job.job.yml`) needs `databricks-sdk[openai]` —
    the gate calls the FM via the serving OpenAI client.
16. **Retail integration tests read real UC tables** (`fact_sales`/`dim_store`). If missing:
    `TABLE_OR_VIEW_NOT_FOUND`. Seed all 3 schemas; `reset_demo.sh` step 2.6 self-heals.
17. **`ruff format --check` is a separate gate** from `ruff check`. Code can pass `check` but
    fail `format --check`. Run `ruff format src/` before pushing.
18. **Demo fixtures must be lint-clean.** The review-blocker fixture had an unused `import os`
    → Ruff F401 failed the deterministic gate, breaking the "only the reviewer blocks" story.
    Bad-PR fixtures must pass linters and carry ONLY the semantic violation.
19. **`/modelops-fix` PR creation needs the App token, not `GITHUB_TOKEN`.** The default
    token can't open PRs unless "Allow Actions to create/approve PRs" is enabled (403). The
    GitHub App identity isn't subject to that — `fix_pr.py` posts `/pulls` with `BOT_TOKEN`.
    (The push already used the App token; only PR creation was on the wrong token.)
20. **`issue_comment` workflows run the workflow file from the DEFAULT branch (main) but
    execute the checked-out PR-head-branch code.** So a fix to `fix_pr.py` only takes effect
    on PR branches recreated from the fixed main — recreate demo PRs (reset) after changing it.
21. **The `demo` label must exist** or `gh pr create --label demo` fails and (if masked) drops
    the PR silently. `reset_demo.sh` creates the label idempotently and surfaces create errors.
22. **The self-hosted runner is single-threaded** — GitHub-side workflow steps queue and drain
    serially (Databricks serverless jobs run off-runner and parallelize fine). Don't push a
    burst of commits right before the demo. Runner dir:
    `/Users/malcoln.dandaro/Documents/Work/Projects/actions-runner` (its registered name has a
    typo, `modeols-cicd-demo`, but it works).

### E. Per-environment training (each env trains its own model)
23. **Job `parameters:` are NOT env vars for a `spark_python_task`.** register/gate/promote
    read catalog/schema; job-level `parameters:` (name/default) never reach `os.environ`, so
    they silently fell back to the dev default and qa/prd trained into `agentic2_mlops_dev`.
    Fix: pass `--catalog ${var.catalog} --schema ${var.schema}` as `spark_python_task.parameters`
    (argv), resolved argv→env→default by `src/ml/_config.py`. ⚠️ importing that sibling via
    module-level `pathlib.Path(__file__)` re-triggers the `__file__` NameError on serverless —
    guard it with a cwd/`databricks.yml` walk-up. And `register.py`'s `--run-id` parse must
    match the flag by NAME (argv now carries `--catalog/--schema` too), not by fixed position.
24. **GLM-5-2 truncation → spurious BLOCK.** The gate's decision JSON was cut off at
    `max_tokens=1200` mid-object → unparseable → `parse_decision` defaulted to a "failed to
    parse" BLOCK that buried the real ML-03 reasoning. Fix: `max_tokens=20000` +
    `_repair_truncated_json` (brute-force close-and-parse) so a truncated response still
    recovers the decision + complete findings.
25. **Cross-env deploy as a human fails on `run_as` binding.** `databricks bundle deploy -t qa`
    (or `-t prd`) run locally as Malcoln errors: the SP `run_as` needs the caller to hold
    `servicePrincipal.user` on the SP. So qa/prd deploys only work IN CI (the deploy runs AS
    the SP → `run_as`=self). Test qa/prd via CI, not local.

## Pointers

- `DEMO.md` — live demo runbook in PT-BR (step-by-step, timings, plan B per failure).
- `.scratch/modelops-cicd-demo/AFK-SESSION-REPORT.md` — chronological record of the
  verification session (local, not committed).
- `docs/ado-translation.md` — GitHub Actions → Azure DevOps parity.
- `scripts/reset_demo.sh` — idempotent reset for all demo state (branches/PRs, UC model across
  dev/staging/prod, experiment grants, seed tables, endpoint cleanup).

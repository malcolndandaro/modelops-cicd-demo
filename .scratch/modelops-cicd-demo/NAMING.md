# Canonical naming map — ModelOps CI/CD demo

Every agent MUST use these names. The mechanical brand pass (bimbops→modelops,
LLM endpoints, workspace host, dotted catalog.schema refs) is DONE. What remains is
judgment rebrand of bare `bimbo` / `bakery` tokens in your assigned files.

## Brand / identity
- Brand: **ModelOps** / `modelops` / `MODELOPS` (done)
- GitHub repo: `malcolndandaro/modelops-cicd-demo` (public)
- DABs bundle name: `bimbo-bakery-pipeline` → **`modelops-cicd-demo`**
- Repo/old tag `bimbo_demo` → `modelops-cicd-demo`

## Databricks environment (VERIFIED)
- CLI profile: `agentic-mlops-cicd-aws`
- Workspace host: `https://dbc-967959c2-d585.cloud.databricks.com`
- Catalog: `malcoln_aws_stable_catalog` (Malcoln owns it)
- Env = schema (NOT catalog-per-env for the live demo):
  - dev     → `agentic2_mlops_dev`
  - qa/staging → `agentic2_mlops_staging`   (workflow target key stays `qa`)
  - prod    → `agentic2_mlops_prod`          (workflow target key stays `prd`)
- LLM endpoint for all calls WE control: `databricks-glm-5-2`
- Embeddings (if needed): `databricks-gte-large-en`

## Serving / UC assets
- Serving endpoint (reviewer agent): `modelops-reviewer` (done)
- UC model (reviewer): `malcoln_aws_stable_catalog.agentic2_mlops_dev.modelops_reviewer`
- Knowledge Assistant endpoint (Gate 1 grounding): **`modelops-handbook-ka`**
  (Agent Bricks KA over the handbook docs; replaces bimbo's raw Vector Search)
- ML model (Gate 2): `malcoln_aws_stable_catalog.<env-schema>.demand_forecaster`
  - aliases: `@champion` (live), `@challenger` (candidate). NO workspace-registry stages.

## Domain rebrand
- `bakery` / `padaria` / `panadería` → **`retail`** (generic demand-forecasting domain)
- dir `src/bakery/` → `src/retail/`
- `data/seed_bakery.py` → `data/seed_retail.py`
- Seed tables `fact_sales` / `dim_store` → keep (already generic)
- Env var prefixes: `BIMBO_TEST_*` → `MODELOPS_TEST_*`; `BIMBO_SEED_*` → `MODELOPS_SEED_*`

## Cross-env hero violation (ENV-01)
- The demo uses schema-per-env, future-state is catalog-per-env.
- In handbook examples, future-state catalogs are generic: `mlops_dev` / `mlops_staging` / `mlops_prod`.
- Bare `bimbo_prd` (future-state prod catalog in examples) → `mlops_prod`.
- The ACTUAL live hero violation in code = a dev asset referencing the prod ENV schema
  `malcoln_aws_stable_catalog.agentic2_mlops_prod.<table>`.

## CI auth (service principal)
- Dedicated OAuth M2M SP. GH repo var `DATABRICKS_SP_CLIENT_ID`, secret `DATABRICKS_CLIENT_SECRET`.
- Repo var `DATABRICKS_HOST` = the workspace host above.
- Bot token secret: `MODELOPS_BOT_TOKEN` (was `BIMBOPS_BOT_TOKEN`).
- Every Databricks-touching CI job runs on the **self-hosted runner** (VPN-only workspace).

## Secret hygiene
- PUBLIC repo. Never commit: SP secret, bot token, or the workspace host is OK to commit
  (it's already public-ish) BUT prefer repo vars. No SCIM/org ids in code.

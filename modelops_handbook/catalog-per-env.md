# Catalog-per-Env — Environment isolation

> Each environment (dev / staging / prod) lives in its own catalog or schema. Code must
> never cross environments or hardcode a catalog name.

### [ENV-01] Referencing another environment's catalog is forbidden
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › Catalog-per-Env › ENV-01

A job running in `dev` or `staging` must never read from or write to a `prod` catalog or
schema (e.g. `*_prod`, `*.prod`, `agentic2_mlops_prod`). Crossing environments breaks
isolation, exposes production data, and lets tests contaminate prod.
❌ `spark.table("malcoln_aws_stable_catalog.agentic2_mlops_prod.gold_pricing")` inside a dev job.
❌ `f"SELECT * FROM malcoln_aws_stable_catalog.agentic2_mlops_prod.gold_pricing"` in code deployed to dev/staging.
✅ Reference the current environment's catalog via a variable: `{catalog}.{schema}.gold_pricing`.

### [ENV-02] Parameterize the catalog and schema with DABs variables
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › Catalog-per-Env › ENV-02

The catalog/schema name is never hardcoded: it is injected as `${var.catalog}` /
`${var.schema}` from the DABs target, or as a job parameter. That way the same code runs in
all three environments without editing a line.
❌ A literal `"malcoln_aws_stable_catalog.agentic2_mlops_dev"` repeated throughout the code.
✅ `dbutils.widgets.get("catalog")` or `${var.catalog}` resolved by the bundle.

### [ENV-03] Do not hardcode workspace URLs or cluster IDs
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › Catalog-per-Env › ENV-03

Workspace hosts, cluster ids, and warehouse ids depend on the environment and must come from
bundle/target variables, never embedded in source code.

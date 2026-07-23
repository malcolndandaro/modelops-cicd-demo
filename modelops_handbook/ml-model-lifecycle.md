# ML Model Lifecycle — Training, registry & promotion standards

> How ML models are trained, versioned, and promoted in ModelOps. These rules govern
> the model-training pipeline and the AI Promotion Gate. The environment boundary is the
> schema (dev / staging / prod) inside a single Unity Catalog catalog; models are governed
> UC assets and the `@champion` alias is production truth.

### [ML-01] A hyperparameter or feature change requires updating the metric-regression test in the same PR
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › ML Model Lifecycle › ML-01

Any change to model hyperparameters or the feature list (e.g. `n_estimators`, `max_depth`,
adding/removing a feature in `src/ml/config.yml`) must be accompanied, in the SAME pull
request, by a corresponding update to the metric-regression test (the hardcoded
`max_acceptable_mae` guard). Changing model behavior without revisiting the quality guard
lets a silent regression through the deterministic gate.
❌ A PR that edits `n_estimators` in `config.yml` but leaves `max_acceptable_mae` and
   `tests/test_demand_forecaster.py` untouched.
✅ The same hyperparameter change WITH an updated threshold (justified in the PR) and a
   passing regression test.

### [ML-02] Models live only in the Unity Catalog registry; the `@champion` alias is moved only by the pipeline
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › ML Model Lifecycle › ML-02

Models are registered to UC as `<catalog>.<schema>.<model>` and referenced by alias. The
`@champion` alias (production truth) is moved ONLY by the promotion pipeline's `promote`
task, after the AI Promotion Gate approves — never by hand in the UI or an ad-hoc notebook.
Manual alias moves bypass the gate and the audit trail.
❌ A notebook or console call that runs `MlflowClient().set_registered_model_alias(..., "champion", version)` manually.
❌ Storing model artifacts outside the UC registry (local pickle, DBFS path) as the source of truth.
✅ The `promote` task moves `@champion` to the challenger version only on gate `APPROVE`.

### [ML-03] Promotion requires the challenger to be no worse than the champion, unless a degradation is justified and approved
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › ML Model Lifecycle › ML-03

A challenger is promoted only if its primary metric is at least as good as the current
champion's (for MAE: challenger MAE ≤ champion MAE — lower error is better). A regression is
allowed only when explicitly justified in the PR/decision and approved by the gate (e.g. a
deliberate trade for lower latency or cost). The first-ever run has no champion and
bootstraps automatically.
❌ Promoting a challenger whose MAE is worse than the champion's with no justification.
✅ Challenger MAE ≤ champion MAE → promote; or a justified degradation the gate approves.

### [ML-04] Training config must not reference another environment's catalog or schema
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › ML Model Lifecycle › ML-04

The training config and ML code must reference only the current environment's schema, always
via the injected `${var.catalog}` / `${var.schema}` (or a job parameter) — never a hardcoded
cross-env target. A dev training run reading or writing the prod schema breaks isolation and
can corrupt the production model or its data. (This is the ML-specific companion to ENV-01.)
❌ `catalog: malcoln_aws_stable_catalog` + `schema: agentic2_mlops_prod` hardcoded in a dev training config.
❌ Registering the dev challenger straight into `...agentic2_mlops_prod.demand_forecaster`.
✅ `schema: ${var.schema}` resolved by the DABs target, so the same config trains per-env.

### [ML-05] Every training run is tracked in MLflow and the promotion decision is traced
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › ML Model Lifecycle › ML-05

Every training run logs to MLflow (metrics, params, the resolved config) with MLflow ≥ 3, and
the AI Promotion Gate instruments its stages with MLflow tracing/spans so the decision inputs
(challenger vs champion metrics, config diff) and the LLM reasoning are auditable in the MLflow
UI. An unlogged run or an untraced promotion decision cannot be reviewed after the fact.
❌ Training a model in a bare script with no `mlflow.start_run()` / metric logging.
✅ `mlflow.sklearn.autolog()` + explicit MAE logging; the gate wraps each stage in `mlflow.start_span`.

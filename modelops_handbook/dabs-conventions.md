# DABs Conventions — Deployment as code

> ModelOps conventions for Databricks Asset Bundles (DABs).

### [DAB-01] Every resource is declared in DABs
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › DABs Conventions › DAB-01

Jobs, pipelines, dashboards, and serving endpoints are defined in the bundle, not created by
hand in the workspace. What is not in the bundle does not exist for CI/CD.

### [DAB-02] One target per environment; run_as SP in staging/prod
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › DABs Conventions › DAB-02

Targets `dev`, `qa` (staging), `prd` (prod) each with their `mode` (development/production). In
staging and prod the `run_as` is the project/CI service principal, not a human user.

### [DAB-03] bundle validate green before merge
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › DABs Conventions › DAB-03

`databricks bundle validate` must pass for every target as part of each PR's quality gate.

# Naming Conventions — Resource and code names

> ModelOps naming conventions for tables, code, and service principals.

### [NM-01] Tables in snake_case with a layer prefix
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › Naming Conventions › NM-01

Tables and views in `snake_case`, with the layer made explicit (`bronze_`, `silver_`,
`gold_`) or by a per-layer schema. E.g. `gold_pricing`, `fact_sales`, `dim_product`.

### [NM-02] Functions and variables in snake_case and descriptive
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › Naming Conventions › NM-02

`snake_case` for functions and variables; names that describe intent. Avoid single-character
names except loop indices.

### [NM-03] Identifiers, comments, and docs in English
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › Naming Conventions › NM-03

Code names (functions, columns, variables), comments, PR descriptions, and team documentation
are all written in English for consistency across the team and tooling.

### [NM-04] Service Principals: sp-<area>-<project>-<env>
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › Naming Conventions › NM-04

Service principals follow `sp-<area>-<project>-<env>`, e.g. `sp-modelops-ci` for the shared CI
identity or `sp-modelops-forecaster-prod` for a per-env project SP. One SP per project and
environment, aligned with the ModelOps identity policy.

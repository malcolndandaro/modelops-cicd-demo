# `bad-pr/` — Intentional anti-examples for the ModelOps CI/CD demo

This directory contains **intentionally invalid or degraded** files used to demonstrate
the two AI gates in the demo. Never import these from production code.

## ML gate scenarios (new)

These are the **primary demo props** — two bad-PR scenarios that demonstrate the two gates:

| Subdirectory | What it does | Gate that catches it | Rule |
|---|---|---|---|
| `ml-review-blocker/` | Hyperparameter change without updating regression test + cross-env prod reference | **Gate 1 BLOCKS** (PR Reviewer) | ML-01, ENV-01 |
| `ml-gate-blocker/` | Clean change that passes review but silently degrades the model | Gate 1 passes, **Gate 2 BLOCKS** (Promotion Gate) | ML-03 |

See the README.md inside each subdirectory for exact file contents, narrative beats, and
how to apply the patches manually.

## Legacy linter anti-examples

These files demonstrate what the deterministic quality gate catches (Ruff, sqlfluff,
`bundle validate`). They are intentionally invalid to show the three layers of deterministic
checks — the AI gates catch what these tools cannot.

| File / folder | Tool that rejects it | Types of violations |
|---|---|---|
| `bad_python.py` | Ruff | Unused imports, mutable defaults, bare except, `== None`, SQL injection (`%`), `assert False` |
| `bad_sql.sql` | sqlfluff (dialect=databricks) | Keywords lowercase, identifiers mixed case, aliases without `AS`, ORDER BY by position, inconsistent spacing |
| `broken_bundle/databricks.yml` | `databricks bundle validate` | Reference to a non-existent variable (`${var.catalogo}` typo) |

## How to run the deterministic linter examples locally

```bash
# From repo root

# 1) Green state — what lives in the real repo
ruff check src/                          # All checks passed!
sqlfluff lint sql/                       # All Finished!
DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t dev  # Validation OK!

# 2) Red state — what the quality gate blocks
ruff check bad-pr/bad_python.py          # 13 errors
sqlfluff lint bad-pr/bad_sql.sql         # many CP01/CP02/CP03/LT01 errors
(cd bad-pr/broken_bundle && DATABRICKS_CONFIG_PROFILE=agentic-mlops-cicd-aws databricks bundle validate -t dev)
                                          # Error: reference does not exist: ${var.catalogo}
```

## How to apply the ML gate scenario patches

Use `scripts/reset_demo.sh --open-prs` to apply them automatically and open PRs. Or apply
manually — see the README.md inside each scenario subdirectory.

## Exclusions

These files are excluded from the normal lint pass:
- `pyproject.toml` → `[tool.ruff] exclude = ["bad-pr"]`
- `.sqlfluff` not linting `bad-pr/` because `sqlfluff lint sql/` uses an explicit path
- The root `databricks.yml` does not include `bad-pr/` (it is a separate bundle)

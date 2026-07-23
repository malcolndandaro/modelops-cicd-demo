# `bad-pr/` — Intentional anti-examples for the ModelOps CI/CD demo

This directory contains **intentionally degraded** files used to demonstrate the two AI
gates in the demo. Never import these from production code.

## The two demo scenarios

These are the demo props — two bad-PR scenarios, each caught by a *different* gate so the
two capabilities are demonstrated in isolation:

| Subdirectory | What it does | Gate that catches it | Rule |
|---|---|---|---|
| `ml-review-blocker/` | A dev-context job hardcodes a **prod** schema reference (`agentic2_mlops_prod.gold_pricing`). Touches no model config, so Gate 2 has nothing to flag — Gate 1 is the *sole* blocker. | **Gate 1 BLOCKS** (PR Reviewer) | ENV-01 |
| `ml-gate-blocker/` | A clean-looking change that passes review (updates `max_acceptable_mae` in the same PR) but silently degrades the model. | Gate 1 passes, **Gate 2 BLOCKS** (Promotion Gate) | ML-03 |

See the `README.md` inside each subdirectory for exact file contents, narrative beats, and
how to apply the patches manually.

## How to apply the scenario patches

Use `scripts/reset_demo.sh --open-prs` to apply them automatically and open the demo PRs.
Or apply manually — see the `README.md` inside each scenario subdirectory.

## Why the fixtures must stay lint-clean

Each fixture carries **only** its intended semantic violation — it must pass Ruff, sqlfluff,
and `bundle validate` so that in the demo *only* the AI gate goes red. (An accidental `import
os` in a fixture would trip Ruff F401 and break the "only the reviewer blocks" story.)

`bad-pr/` is excluded from the normal lint pass via `pyproject.toml` → `[tool.ruff] exclude`.

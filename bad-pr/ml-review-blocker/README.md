# bad-pr/ml-review-blocker — Scenario 1: Gate 1 (the reviewer) blocks

## What this PR changes

A pull request that is **syntactically clean and touches no model config** — it only adds a
pricing-reference lookup to `src/jobs/pricing_adjustments.py` that hardcodes the **prod**
schema `malcoln_aws_stable_catalog.agentic2_mlops_prod.gold_pricing` from a **dev**-context
job. A pure cross-environment (ENV-01) policy violation.

> Scenario 1 deliberately does **NOT** change `src/ml/config.yml` — no hyperparameter/model
> change — so the AI Promotion Gate (Gate 2) has nothing to flag and stays green. The
> **reviewer (Gate 1) is the sole blocker.** The model-quality path (ML-03) is scenario 2,
> `ml-gate-blocker`.

## Files in this scenario

| File | Maps to (repo path) | What it changes |
|---|---|---|
| `pricing_adjustments.py` | `src/jobs/pricing_adjustments.py` | Adds `PROD_PRICING_REF = "...agentic2_mlops_prod.gold_pricing"` (hardcoded prod ref) |

## Which gate catches it

| Check | Result |
|---|---|
| Ruff / sqlfluff / `bundle validate` | ✅ pass (syntactically clean) |
| `deploy + integration tests + Gate 2 (dev)` | ✅ pass (no model change → gate APPROVEs) |
| **ModelOps Reviewer** (Gate 1 Check Run) | 🔴 **failure — ENV-01 BLOCKER** |

**Finding:** ENV-01 (`Catalog-per-Env`) — a dev job must never read from a prod
catalog/schema. Suggestion: use `${var.catalog}.${var.schema}.gold_pricing`.

## Narrative beat

> "The linters pass green — Ruff, sqlfluff, `bundle validate` — and even the AI Promotion
> Gate is green because no model config changed. The PR looks clean. Only Gate 1, grounded
> on the ModelOps Handbook via the Knowledge Assistant, catches the semantic ENV-01
> violation that deterministic tools cannot see."

After Gate 1 blocks, the presenter comments `/modelops-fix`: the bot (GitHub App) opens a fix
PR against this PR's branch rewriting the hardcoded prod reference to the DABs-variable form,
which re-triggers Gate 1 to pass.

## How to apply this scenario (for demo setup)

`scripts/reset_demo.sh --open-prs` recreates the `demo/ml-review-blocker` branch (only
`pricing_adjustments.py` changes) and opens the PR automatically.

# bad-pr/ml-review-blocker — Scenario 1: Gate 1 blocks

## What this PR changes

This scenario simulates a developer changing a hyperparameter (`n_estimators: 100 → 200`)
in `src/ml/config.yml` WITHOUT updating the regression test threshold (`max_acceptable_mae`
in the same file and/or `tests/test_demand_forecaster.py`). It also adds a cross-environment
reference in `src/jobs/pricing_adjustments.py`: a dev-context job reads the **prod schema**
`agentic2_mlops_prod.gold_pricing` directly, hardcoded.

## Files in this scenario

| File | Maps to (repo path) | What it changes |
|---|---|---|
| `config.yml` | `src/ml/config.yml` | `n_estimators` changed to 200; `max_acceptable_mae` NOT updated |
| `pricing_adjustments.py` | `src/jobs/pricing_adjustments.py` | Adds `PROD_PRICING_REF = "...agentic2_mlops_prod.gold_pricing"` (hardcoded prod ref) |

## Which gate catches it

**Gate 1 — PR Reviewer** BLOCKS with two findings:

| Finding | Rule | Severity |
|---|---|---|
| `n_estimators` changed without updating `max_acceptable_mae` in config.yml and `tests/test_demand_forecaster.py` | **ML-01** (hyperparameter change requires regression test update in same PR) | BLOCKER |
| `PROD_PRICING_REF` references `agentic2_mlops_prod` from a dev-context job | **ENV-01** (cross-environment catalog/schema reference forbidden) | BLOCKER |

## Narrative beat

> "The linters pass green — Ruff, sqlfluff, `bundle validate` all succeed. The PR looks
> clean syntactically. Only Gate 1, grounded on the ModelOps Handbook via the Knowledge
> Assistant, catches the two policy violations. This is the semantic gap deterministic
> tools cannot fill."

After Gate 1 blocks, the presenter runs `/modelops-fix` to show the self-correcting loop:
the bot opens a new fix PR that corrects both issues, which re-triggers Gate 1 to pass.

## How to apply this scenario (for demo setup)

The `scripts/reset_demo.sh --open-prs` script applies these patches to a `demo/ml-review-blocker`
branch and opens the PR automatically. To apply manually:

```bash
git checkout -b demo/ml-review-blocker main
cp bad-pr/ml-review-blocker/config.yml src/ml/config.yml
cp bad-pr/ml-review-blocker/pricing_adjustments.py src/jobs/pricing_adjustments.py
git add src/ml/config.yml src/jobs/pricing_adjustments.py
git commit -m "demo: increase n_estimators and add pricing reference (review-blocker scenario)"
git push origin demo/ml-review-blocker
gh pr create --base main --head demo/ml-review-blocker \
  --title "feat: tune demand_forecaster and add pricing reference" \
  --body "Increases n_estimators to 200 for better accuracy. Also adds pricing reference lookup." \
  --label demo
```

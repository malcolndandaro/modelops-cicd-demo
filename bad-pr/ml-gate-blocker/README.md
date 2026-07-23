# bad-pr/ml-gate-blocker — Scenario 2: Gate 2 blocks

## What this PR changes

This scenario simulates a "clean" change that passes all linters AND Gate 1 (no policy
violations), but silently degrades the `demand_forecaster` model:

- `n_estimators` is slashed from 100 to 5 (dramatically underfits the model).
- 6 of 8 input features are dropped (only `day_of_week` and `store_id` remain).
- `max_acceptable_mae` is inflated from 12.0 to 50.0 — this makes the regression test
  assertion pass (the PR looks clean) but hides the real degradation.

## Files in this scenario

| File | Maps to (repo path) | What it changes |
|---|---|---|
| `config.yml` | `src/ml/config.yml` | `n_estimators` → 5; features list drastically shortened; `max_acceptable_mae` → 50.0 |

## Which gate catches it

**Gate 1 — PR Reviewer** passes: no policy violation — the config change is syntactically
valid, `max_acceptable_mae` was updated in the same PR (satisfies ML-01 check), and there
are no cross-env references.

**Gate 2 — Promotion Gate** BLOCKS with:

| Finding | Rule | Severity |
|---|---|---|
| Challenger MAE significantly worse than champion (e.g., 35+ vs champion's 8–10) | **ML-03** (challenger must meet or beat champion metrics) | BLOCKER |

## Narrative beat

> "Gate 1 is green — the PR is technically correct. The change is even well-intentioned on
> paper ('reducing complexity'). But Gate 2 trained the challenger, compared it to the
> current champion, and the numbers don't lie: MAE went from ~10 to ~38. The promotion is
> blocked. The @champion alias stays on the proven model. This is why Gate 2 exists —
> it catches what policy checks alone cannot."

The decision is MLflow-traced: the presenter can show the reasoning in the MLflow UI,
including the metric diff and the cited ML-03 finding.

## How to apply this scenario (for demo setup)

The `scripts/reset_demo.sh --open-prs` script applies these patches to a `demo/ml-gate-blocker`
branch and opens the PR automatically. To apply manually:

```bash
git checkout -b demo/ml-gate-blocker main
cp bad-pr/ml-gate-blocker/config.yml src/ml/config.yml
git add src/ml/config.yml
git commit -m "demo: simplify demand_forecaster config for faster inference (gate-blocker scenario)"
git push origin demo/ml-gate-blocker
gh pr create --base main --head demo/ml-gate-blocker \
  --title "perf: simplify demand_forecaster — reduce estimators and feature set" \
  --body "Reduces model complexity by cutting n_estimators and focusing on the most predictive features. Updates MAE threshold accordingly." \
  --label demo
```

## Verification: this scenario really degrades the model

You can verify locally (no workspace needed):

```bash
# From repo root — compare the two configs
python -c "
import sys; sys.path.insert(0, 'src/ml')
from train import load_config, make_dataset
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import yaml

for label, path in [('main (good)', 'src/ml/config.yml'), ('gate-blocker', 'bad-pr/ml-gate-blocker/config.yml')]:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    hp = cfg['hyperparameters']
    X, y = make_dataset(cfg['features'], random_state=hp['random_state'])
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=hp['random_state'])
    m = RandomForestRegressor(n_estimators=hp['n_estimators'], max_depth=hp['max_depth'],
                               min_samples_leaf=hp['min_samples_leaf'], random_state=hp['random_state'])
    m.fit(Xtr, ytr)
    mae = mean_absolute_error(yte, m.predict(Xte))
    print(f'{label}: MAE={mae:.2f} (threshold={cfg[\"max_acceptable_mae\"]})')
"
```

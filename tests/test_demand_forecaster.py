"""Metric-regression test for the demand_forecaster model.

This test is a DEMO PROP as well as a real quality gate:

  Bad PR #1 (review-blocker): Changes a hyperparameter in config.yml WITHOUT
      updating max_acceptable_mae here — Gate 1 (PR Reviewer) flags it as ML-02
      BLOCKER ("config change requires regression test update in same PR").

  Bad PR #2 (gate-blocker): A config change that looks clean (test threshold was
      updated to match) but actually degrades the model — Gate 2 (Promotion Gate)
      catches what the threshold test alone missed.

If you change hyperparameters or the feature list in src/ml/config.yml, you MUST
update max_acceptable_mae in config.yml AND re-validate this assertion in the same PR.
"""

import pathlib
import sys

# Support running from repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src" / "ml"))

from sklearn.ensemble import RandomForestRegressor  # noqa: E402
from sklearn.metrics import mean_absolute_error  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402
from train import load_config, make_dataset  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _train_and_evaluate(config: dict) -> float:
    """Train the demand_forecaster locally and return MAE on the holdout set.

    Uses the same hyperparameters and feature list as train.py so the test
    reflects what the training job will actually produce.
    """
    hp = config["hyperparameters"]
    features = config["features"]

    X, y = make_dataset(features, random_state=hp["random_state"])
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=hp["random_state"]
    )
    model = RandomForestRegressor(
        n_estimators=hp["n_estimators"],
        max_depth=hp["max_depth"],
        min_samples_leaf=hp["min_samples_leaf"],
        random_state=hp["random_state"],
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    return float(mean_absolute_error(y_test, preds))


# ---------------------------------------------------------------------------
# The metric-regression gate
# ---------------------------------------------------------------------------

def test_demand_forecaster_mae_within_threshold():
    """Assert that the demand_forecaster meets the MAE threshold in config.yml.

    This is the CANONICAL regression test for Gate 2.

    If this test fails:
      - You changed config.yml (hyperparameters or features) and the model is
        worse than the allowed threshold.
      - Fix: either improve the model config until MAE is within threshold, OR
        if the change is intentional, update max_acceptable_mae in config.yml
        AND document the justification in the same PR (required by ML-02).

    The test is deterministic (fixed random_state) so it never flaps.
    """
    config = load_config()
    max_acceptable_mae = config["max_acceptable_mae"]

    actual_mae = _train_and_evaluate(config)

    print(f"\nDemand forecaster MAE: {actual_mae:.4f} (threshold: {max_acceptable_mae})")

    assert actual_mae <= max_acceptable_mae, (
        f"Model MAE {actual_mae:.4f} exceeds max_acceptable_mae {max_acceptable_mae}. "
        f"Either fix the model config or update max_acceptable_mae in src/ml/config.yml "
        f"with a justification in the same PR (ML-02)."
    )


def test_config_has_required_keys():
    """Config.yml must define model_name, hyperparameters, features, and max_acceptable_mae."""
    config = load_config()
    for key in ("model_name", "hyperparameters", "features", "max_acceptable_mae"):
        assert key in config, f"src/ml/config.yml is missing required key: {key}"


def test_config_features_non_empty():
    """Feature list must be non-empty — an empty feature list is a config error."""
    config = load_config()
    assert len(config["features"]) > 0, "Feature list in src/ml/config.yml must not be empty."


def test_config_hyperparameters_positive():
    """Hyperparameters must have positive integer values — negative values are config errors."""
    hp = load_config()["hyperparameters"]
    assert hp["n_estimators"] > 0, "n_estimators must be > 0"
    assert hp["max_depth"] > 0, "max_depth must be > 0"
    assert hp["min_samples_leaf"] > 0, "min_samples_leaf must be > 0"


def test_config_max_acceptable_mae_positive():
    """Threshold must be positive."""
    config = load_config()
    assert config["max_acceptable_mae"] > 0, "max_acceptable_mae must be > 0"

"""Gate 2 — Step 1: train a demand-forecasting model and log it with MLflow 3.

Reads hyperparameters and feature config from src/ml/config.yml.
Generates a deterministic synthetic dataset inline (no external dependency).
Logs the run to MLflow with autolog + explicit MAE metric and the config artifact.
The resulting run URI is printed so the register step can locate it.

Usage (serverless task):
    python src/ml/train.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from typing import Any

import mlflow
import mlflow.sklearn
import numpy as np
import yaml
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _repo_root() -> pathlib.Path:
    """Resolve the repo root, robust to `__file__` being undefined.

    Databricks runs a spark_python_task via exec(compile(...)), so `__file__` is not
    defined there (NameError). Locally it is. Fall back to walking up from cwd for the
    `databricks.yml` marker (DABs syncs the whole tree under the deploy files root).
    """
    try:
        candidate = pathlib.Path(__file__).resolve().parents[2]
        if (candidate / "databricks.yml").exists():
            return candidate
    except NameError:
        pass
    cwd = pathlib.Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if (d / "databricks.yml").exists():
            return d
    return cwd


_REPO_ROOT = _repo_root()
_CONFIG_PATH = _REPO_ROOT / "src" / "ml" / "config.yml"


def load_config() -> dict[str, Any]:
    """Load versioned training config from src/ml/config.yml."""
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _ensure_experiment_parent(experiment_name: str) -> None:
    """Create the experiment's parent workspace folder if it doesn't exist.

    `mlflow.set_experiment("/ModelOps/...")` fails with NOT_FOUND if the parent
    directory `/ModelOps` doesn't exist — set_experiment does not create intermediate
    workspace folders. Idempotent: mkdirs is a no-op if the folder already exists.
    Best-effort — if the SDK isn't available or the call fails, let set_experiment surface.
    """
    parent = experiment_name.rsplit("/", 1)[0]
    if not parent or "/" not in experiment_name:
        return
    try:
        from databricks.sdk import WorkspaceClient

        WorkspaceClient().workspace.mkdirs(parent)
    except Exception as e:  # noqa: BLE001 — best-effort; set_experiment will report if it matters
        print(f"could not pre-create experiment parent {parent}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Synthetic data generation — deterministic, self-contained
# ---------------------------------------------------------------------------

_N_ROWS = 5_000
_N_STORES = 20
_CATEGORIES = [0, 1, 2, 3, 4]  # encoded product categories


def make_dataset(features: list[str], random_state: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate a synthetic retail demand dataset.

    Returns (X, y) arrays suitable for train/test split.  Distributions are
    intentionally non-trivial so MAE is a meaningful signal: sales are driven by
    weekday, seasonality, promotions, and a lag feature — the same pattern a real
    demand model would learn.
    """
    rng = np.random.default_rng(random_state)
    n = _N_ROWS

    day_of_week = rng.integers(0, 7, size=n)
    week_of_year = rng.integers(1, 53, size=n)
    store_id = rng.integers(0, _N_STORES, size=n)
    product_category = rng.choice(_CATEGORIES, size=n)
    price = rng.uniform(1.0, 50.0, size=n)
    promotion_flag = rng.integers(0, 2, size=n)

    # Base demand: weekday lift, seasonal peak, store effect
    base = (
        20.0
        + 5.0 * (day_of_week < 2).astype(float)  # weekend boost
        + 3.0 * np.sin(2 * np.pi * week_of_year / 52)  # seasonality
        + store_id * 0.3  # store size effect
        - 0.4 * price  # price elasticity
        + 4.0 * promotion_flag  # promotion lift
        + 2.0 * product_category  # category baseline
    )

    # Lag features: simulate 7- and 14-day lags with noise
    lag_7d_sales = base + rng.normal(0, 2.0, size=n)
    lag_14d_sales = base + rng.normal(0, 3.0, size=n)

    # Target: actual sales with realistic noise
    y = np.clip(base + rng.normal(0, 4.0, size=n), 0, None)

    _col_map = {
        "day_of_week": day_of_week,
        "week_of_year": week_of_year,
        "store_id": store_id,
        "product_category": product_category,
        "price": price,
        "promotion_flag": promotion_flag,
        "lag_7d_sales": lag_7d_sales,
        "lag_14d_sales": lag_14d_sales,
    }
    X = np.column_stack([_col_map[f] for f in features])
    return X, y


# ---------------------------------------------------------------------------
# Training entry point
# ---------------------------------------------------------------------------

def train(config: dict[str, Any]) -> str:
    """Train the demand forecaster, log to MLflow, return the run ID."""
    hp = config["hyperparameters"]
    features: list[str] = config["features"]
    max_mae: float = config["max_acceptable_mae"]

    mlflow.sklearn.autolog(log_input_examples=False, silent=True)

    experiment_name = os.environ.get(
        "MLFLOW_EXPERIMENT_NAME", "/ModelOps/demand_forecaster_training"
    )
    _ensure_experiment_parent(experiment_name)
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name="demand_forecaster_train") as run:
        # Log the config as an artifact for the promotion diff
        mlflow.log_artifact(str(_CONFIG_PATH), artifact_path="config")

        # Log config values as params for diff-ability in the UI
        mlflow.log_params(
            {
                "n_estimators": hp["n_estimators"],
                "max_depth": hp["max_depth"],
                "min_samples_leaf": hp["min_samples_leaf"],
                "random_state": hp["random_state"],
                "features": json.dumps(features),
                "max_acceptable_mae": max_mae,
            }
        )

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
        mae = float(mean_absolute_error(y_test, preds))

        # Explicit metric log (autolog also logs it, this ensures the key name)
        mlflow.log_metric("mae", mae)
        mlflow.log_metric("max_acceptable_mae", max_mae)
        mlflow.log_metric("mae_within_threshold", float(mae <= max_mae))

        # Log feature list as a tag for retrieval by the promotion gate
        mlflow.set_tag("features", json.dumps(features))
        mlflow.set_tag("model_name", config["model_name"])

        print(f"Training complete — MAE: {mae:.4f} (threshold: {max_mae})")
        if mae > max_mae:
            print(
                f"WARNING: MAE {mae:.4f} exceeds max_acceptable_mae {max_mae}. "
                "The metric-regression test will fail. Review your config changes."
            )

        run_id = run.info.run_id

    print(f"MLflow run_id: {run_id}")
    return run_id


def main() -> None:
    config = load_config()
    run_id = train(config)
    # Best-effort: hand the run_id to the register task via a temp file. On serverless,
    # tasks do NOT share a local filesystem and /tmp may be read-only — so this is only a
    # convenience. register.py's authoritative path is get_latest_run_id() (looks the run
    # up by experiment + tags.model_name), so a failed write here is harmless.
    try:
        output_path = pathlib.Path(tempfile.gettempdir()) / "demand_forecaster_run_id.txt"
        output_path.write_text(run_id)
        print(f"Run ID written to {output_path}")
    except OSError as e:
        print(f"(run_id file not written — register.py resolves it by experiment: {e})")


if __name__ == "__main__":
    sys.exit(main())

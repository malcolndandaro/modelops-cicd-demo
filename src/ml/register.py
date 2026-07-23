"""Gate 2 — Step 2: register the trained model to Unity Catalog with @challenger alias.

Finds the most recent MLflow run tagged with model_name=demand_forecaster in the
training experiment, registers it to UC as:
    <catalog>.<schema>.demand_forecaster
and assigns the new version the @challenger alias.

NOTE: UC aliases (@champion / @challenger) are used exclusively — workspace-registry
"stage transitions" (Staging/Production) are the deprecated predecessor and are NOT used.
When customers ask about "stage transitions", point to aliases as the current best practice.

Usage (serverless task):
    python src/ml/register.py [--run-id <mlflow-run-id>]

Environment variables (set by DABs job parameters):
    MLFLOW_CATALOG   — UC catalog (default: malcoln_aws_stable_catalog)
    MLFLOW_SCHEMA    — UC schema  (default: agentic2_mlops_dev)
"""

from __future__ import annotations

import os
import pathlib
import sys

import mlflow
from mlflow import MlflowClient


def _ml_dir() -> pathlib.Path:
    """Locate src/ml, robust to `__file__` being undefined on serverless spark_python_task."""
    try:
        return pathlib.Path(__file__).resolve().parent
    except NameError:
        cwd = pathlib.Path.cwd().resolve()
        for d in (cwd, *cwd.parents):
            if (d / "databricks.yml").exists():
                return d / "src" / "ml"
        return cwd


sys.path.insert(0, str(_ml_dir()))
from _config import resolve_catalog_schema  # noqa: E402

# ---------------------------------------------------------------------------
# Config: --catalog/--schema args (from the DABs task) → MLFLOW_* env → dev default
# ---------------------------------------------------------------------------

CATALOG, SCHEMA = resolve_catalog_schema()
MODEL_NAME = "demand_forecaster"
REGISTERED_MODEL_FQN = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", "/ModelOps/demand_forecaster_training")


def get_latest_run_id() -> str:
    """Find the most recent completed run in the training experiment."""
    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        raise RuntimeError(
            f"Experiment '{EXPERIMENT_NAME}' not found. "
            "Run train.py first to create the experiment and a training run."
        )
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string="tags.model_name = 'demand_forecaster'",
        order_by=["start_time DESC"],
        max_results=1,
    )
    if not runs:
        raise RuntimeError(
            "No completed demand_forecaster training run found. " "Run train.py first."
        )
    return runs[0].info.run_id


def register_and_alias(run_id: str) -> int:
    """Register the run's sklearn model to UC and assign @challenger alias.

    Returns the newly registered version number.
    """
    mlflow.set_registry_uri("databricks-uc")

    model_uri = f"runs:/{run_id}/model"
    print(f"Registering model from run {run_id} to {REGISTERED_MODEL_FQN} ...")

    mv = mlflow.register_model(
        model_uri=model_uri,
        name=REGISTERED_MODEL_FQN,
    )
    version = int(mv.version)
    print(f"Registered as version {version}")

    # Assign @challenger alias — the gate decides whether to move @champion.
    # NOTE: we use UC aliases, not deprecated workspace-registry stages.
    client = MlflowClient()
    client.set_registered_model_alias(
        name=REGISTERED_MODEL_FQN,
        alias="challenger",
        version=str(version),
    )
    print(f"Alias @challenger -> version {version}")
    return version


def main() -> None:
    run_id: str | None = None

    # Accept --run-id <id> anywhere in argv (argv also carries --catalog/--schema now,
    # so match the flag by name rather than by fixed position).
    if "--run-id" in sys.argv:
        i = sys.argv.index("--run-id")
        if i + 1 < len(sys.argv):
            run_id = sys.argv[i + 1]

    if not run_id:
        # Fallback: read from the file written by train.py (best-effort; /tmp not shared)
        run_id_file = pathlib.Path("/tmp/demand_forecaster_run_id.txt")  # noqa: S108
        if run_id_file.exists():
            run_id = run_id_file.read_text().strip()

    if not run_id:
        run_id = get_latest_run_id()

    print(f"Using run_id: {run_id}")
    version = register_and_alias(run_id)
    print(f"Registration complete: {REGISTERED_MODEL_FQN} version {version} @challenger")


if __name__ == "__main__":
    # Call main() directly: on the serverless notebook exec wrapper, raising SystemExit
    # (even with code 0/None) is reported as a task failure.
    main()

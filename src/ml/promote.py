"""Gate 2 — Step 4: promote the @challenger model to @champion.

This task only runs when the promotion_gate task exits 0 (APPROVE).
If the gate returned exit code 1 (BLOCK), the DABs job fails and this task
is never executed.

NOTE on alias semantics:
    @champion  — the live version currently serving inference.  Moved here on APPROVE.
    @challenger — the candidate just registered by register.py.

    UC aliases are used exclusively.  Workspace-registry "stage transitions"
    (Staging → Production in the deprecated model registry) are NOT used.
    When customers ask about "stage transitions", this is the current best practice:
    aliases are lightweight named pointers to a version number within UC.

Usage (serverless task):
    python src/ml/promote.py
"""

from __future__ import annotations

import pathlib
import sys

import mlflow
from mlflow import MlflowClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _config import resolve_catalog_schema  # noqa: E402

# ---------------------------------------------------------------------------
# Config: --catalog/--schema args (from the DABs task) → MLFLOW_* env → dev default
# ---------------------------------------------------------------------------

CATALOG, SCHEMA = resolve_catalog_schema()
MODEL_NAME = "demand_forecaster"
REGISTERED_MODEL_FQN = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"


def promote_challenger_to_champion() -> None:
    """Move the @champion alias to the version currently aliased @challenger.

    Steps:
        1. Resolve @challenger to a version number.
        2. Assign @champion to that version number.
        3. Log the transition.
    """
    mlflow.set_registry_uri("databricks-uc")
    client = MlflowClient()

    # Resolve @challenger
    try:
        challenger_mv = client.get_model_version_by_alias(REGISTERED_MODEL_FQN, "challenger")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Cannot promote: @challenger alias not found on {REGISTERED_MODEL_FQN}. "
            "Run register.py first. Original error: {e}"
        ) from e

    challenger_version = challenger_mv.version
    print(f"Challenger version to promote: {challenger_version}")

    # Capture existing champion version for the log
    try:
        old_champion = client.get_model_version_by_alias(REGISTERED_MODEL_FQN, "champion")
        old_champion_version = old_champion.version
        print(f"Previous champion version: {old_champion_version}")
    except Exception:  # noqa: BLE001 — no existing champion is fine (bootstrap)
        old_champion_version = None
        print("No existing @champion — establishing first champion (bootstrap).")

    # Move @champion to the challenger version
    # NOTE: set_registered_model_alias automatically releases the alias from
    # any previous version (aliases can only point to one version at a time).
    client.set_registered_model_alias(
        name=REGISTERED_MODEL_FQN,
        alias="champion",
        version=str(challenger_version),
    )
    print(f"@champion alias -> version {challenger_version}")
    print(
        f"Promotion complete: {REGISTERED_MODEL_FQN} "
        f"v{old_champion_version or '(none)'} -> v{challenger_version}"
    )


def main() -> None:
    promote_challenger_to_champion()
    print("Promote task finished successfully.")


if __name__ == "__main__":
    # Call main() directly: on the serverless notebook exec wrapper, raising SystemExit
    # (even with code 0/None) is reported as a task failure.
    main()

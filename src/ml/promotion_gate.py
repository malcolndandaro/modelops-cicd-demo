"""Gate 2 — Step 3: AI promotion gate (imperative shell).

Reads challenger @challenger and champion @champion metrics from MLflow,
builds a promotion prompt via promotion_core, calls the LLM (databricks-glm-5-2),
and parses the structured APPROVE/BLOCK decision.

All stages are instrumented with MLflow 3 tracing so the reasoning is visible
in the MLflow UI during the demo.

Exit codes:
    0  — APPROVE (let the 'promote' task run in the DABs job)
    1  — BLOCK   (job fails here; promote task does not run)

Usage (serverless task):
    python src/ml/promotion_gate.py
"""

from __future__ import annotations

import os
import pathlib
import sys

import mlflow
from mlflow import MlflowClient
from mlflow.deployments import get_deploy_client

# ---------------------------------------------------------------------------
# Lazy import of promotion_core — supports both installed-package and
# direct-script execution from the repo root (serverless task)
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src" / "ml"))

import promotion_core  # noqa: E402  (after sys.path insert)

# ---------------------------------------------------------------------------
# Environment config (injected by DABs job parameters)
# ---------------------------------------------------------------------------

CATALOG = os.environ.get("MLFLOW_CATALOG", "malcoln_aws_stable_catalog")
SCHEMA = os.environ.get("MLFLOW_SCHEMA", "agentic2_mlops_dev")
MODEL_NAME = "demand_forecaster"
REGISTERED_MODEL_FQN = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

LLM_ENDPOINT = "databricks-glm-5-2"

# TODO: read ML rules from modelops_handbook/ml-model-lifecycle.md once it is
# added by the handbook teammate.  See modelops_handbook/ and spec issue 0001.
# For now the inline DEFAULT_ML_RULES from promotion_core are used.
_HANDBOOK_PATH = _REPO_ROOT / "modelops_handbook" / "ml-model-lifecycle.md"


def _load_ml_rules() -> str:
    """Load ML handbook rules from the handbook file, fall back to inline defaults."""
    if _HANDBOOK_PATH.exists():
        try:
            text = _HANDBOOK_PATH.read_text()
            print(f"Loaded ML rules from {_HANDBOOK_PATH}")
            return text
        except OSError as e:
            print(f"Could not read handbook file: {e}. Using inline defaults.")
    else:
        print(
            f"Handbook file not found at {_HANDBOOK_PATH}. Using inline defaults. "
            "(Add modelops_handbook/ml-model-lifecycle.md to enable grounded rules.)"
        )
    return promotion_core.DEFAULT_ML_RULES


# ---------------------------------------------------------------------------
# Metric retrieval helpers
# ---------------------------------------------------------------------------

def _get_version_metrics(client: MlflowClient, alias: str) -> dict | None:
    """Fetch MLflow metrics for the model version with the given alias.

    Returns a metric dict or None if the alias does not exist.
    """
    try:
        mv = client.get_model_version_by_alias(REGISTERED_MODEL_FQN, alias)
    except Exception:  # noqa: BLE001 — alias not found is the bootstrap case
        return None

    run = client.get_run(mv.run_id)
    metrics = dict(run.data.metrics)
    metrics["version"] = int(mv.version)
    metrics["run_id"] = mv.run_id
    return metrics


def _get_config_diff(
    challenger_run_id: str | None,
    champion_run_id: str | None,
    client: MlflowClient,
) -> str:
    """Produce a text diff of config.yml artifacts between the two runs.

    Falls back to a placeholder if artifacts are not available.
    """
    if not champion_run_id:
        return "(no champion — first deployment)"
    if not challenger_run_id:
        return "(challenger run ID unavailable — cannot compute diff)"

    # Download config artifacts and diff them inline
    import difflib
    import tempfile

    def _download_config(run_id: str) -> str | None:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                local = client.download_artifacts(run_id, "config/config.yml", tmpdir)
                return pathlib.Path(local).read_text()
        except Exception:  # noqa: BLE001
            return None

    challenger_cfg = _download_config(challenger_run_id)
    champion_cfg = _download_config(champion_run_id)

    if challenger_cfg is None or champion_cfg is None:
        return "(config artifacts not available — no diff)"
    if challenger_cfg == champion_cfg:
        return "(no config changes between challenger and champion)"

    diff_lines = list(
        difflib.unified_diff(
            champion_cfg.splitlines(keepends=True),
            challenger_cfg.splitlines(keepends=True),
            fromfile="champion/config.yml",
            tofile="challenger/config.yml",
        )
    )
    return "".join(diff_lines[:100])  # cap at 100 lines for the prompt


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(system: str, user: str) -> str:
    """Call databricks-glm-5-2 with the promotion prompt."""
    client = get_deploy_client("databricks")
    resp = client.predict(
        endpoint=LLM_ENDPOINT,
        inputs={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1200,
        },
    )
    return resp["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Gate entry point — instrumented with MLflow 3 tracing
# ---------------------------------------------------------------------------

def run_gate() -> None:
    """Run the promotion gate.  Exits 0 on APPROVE, 1 on BLOCK."""
    mlflow.set_registry_uri("databricks-uc")

    experiment_name = os.environ.get(
        "MLFLOW_EXPERIMENT_NAME", "/ModelOps/demand_forecaster_training"
    )
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name="promotion_gate") as run:
        print(f"Promotion gate run: {run.info.run_id}")

        client = MlflowClient()

        # --- Span 1: collect metrics ----------------------------------------
        with mlflow.start_span("collect_metrics") as span:
            challenger_metrics = _get_version_metrics(client, "challenger")
            champion_metrics = _get_version_metrics(client, "champion")

            champion_exists = champion_metrics is not None
            span.set_attributes(
                {
                    "champion_exists": champion_exists,
                    "challenger_version": str(
                        challenger_metrics.get("version") if challenger_metrics else "?"
                    ),
                    "champion_version": str(
                        champion_metrics.get("version") if champion_metrics else "none"
                    ),
                }
            )

        if challenger_metrics is None:
            print("ERROR: No @challenger alias found. Run register.py first.")
            sys.exit(1)

        # --- Bootstrap check -----------------------------------------------
        bootstrap = promotion_core.bootstrap_decision(champion_exists)
        if bootstrap is not None:
            print("Bootstrap: no champion found — auto-approving.")
            print(f"Justification: {bootstrap['justification']}")
            mlflow.log_param("gate_decision", "APPROVE_BOOTSTRAP")
            sys.exit(0)

        # --- Span 2: metric comparison + config diff -----------------------
        with mlflow.start_span("build_prompt") as span:
            challenger_mae = challenger_metrics.get("mae", float("inf"))
            champion_mae = champion_metrics.get("mae", float("inf"))

            comparison = promotion_core.compare_metrics(challenger_mae, champion_mae)
            print(f"Metric comparison: {comparison['summary']}")

            ml_rules = _load_ml_rules()

            challenger_run_id = challenger_metrics.get("run_id")
            champion_run_id = champion_metrics.get("run_id")
            config_diff = _get_config_diff(challenger_run_id, champion_run_id, client)

            system_prompt, user_prompt = promotion_core.build_promotion_prompt(
                challenger_metrics={
                    k: v
                    for k, v in challenger_metrics.items()
                    if k not in ("version", "run_id")
                },
                champion_metrics={
                    k: v
                    for k, v in champion_metrics.items()
                    if k not in ("version", "run_id")
                },
                config_diff=config_diff,
                ml_rules=ml_rules,
            )
            span.set_attributes(
                {
                    "challenger_mae": challenger_mae,
                    "champion_mae": champion_mae,
                    "metric_delta": comparison["delta"],
                    "metric_better": comparison["better"],
                }
            )

        # --- Span 3: LLM call -----------------------------------------------
        with mlflow.start_span("llm_call") as span:
            print(f"Calling LLM endpoint: {LLM_ENDPOINT} ...")
            raw_response = _call_llm(system_prompt, user_prompt)
            span.set_attribute("llm_endpoint", LLM_ENDPOINT)
            span.set_attribute("response_length", len(raw_response))

        # --- Span 4: parse decision -----------------------------------------
        with mlflow.start_span("parse_decision") as span:
            decision_obj = promotion_core.parse_decision(raw_response)
            decision = decision_obj["decision"]
            findings = decision_obj["findings"]
            justification = decision_obj["justification"]

            span.set_attributes(
                {
                    "decision": decision,
                    "n_findings": len(findings),
                }
            )

        # Log decision to MLflow run
        mlflow.log_param("gate_decision", decision)
        mlflow.log_param("n_findings", len(findings))
        mlflow.log_text(justification, "gate_justification.txt")
        mlflow.log_text(raw_response, "llm_raw_response.txt")

        # --- Print full parecer ----------------------------------------------
        print("\n" + "=" * 60)
        print("PROMOTION GATE DECISION")
        print("=" * 60)
        print(f"Decision:       {decision}")
        print(f"Justification:  {justification}")
        if findings:
            print("\nFindings:")
            for f in findings:
                sev = f.get("severity", "?")
                rid = f.get("rule_id", "?")
                msg = f.get("message", "")
                print(f"  [{sev}] {rid}: {msg}")
        print(f"\nChallenger version: {challenger_metrics.get('version')}")
        if champion_metrics:
            print(f"Champion version:   {champion_metrics.get('version')}")
        print(f"Metric comparison:  {comparison['summary']}")
        print("=" * 60 + "\n")

    if decision == "APPROVE":
        print("Gate APPROVED — the promote task will run.")
        sys.exit(0)
    else:
        print("Gate BLOCKED — promotion denied. See findings above.")
        print("The 'promote' task will NOT run (job fails here).")
        sys.exit(1)


def main() -> None:
    run_gate()


if __name__ == "__main__":
    main()

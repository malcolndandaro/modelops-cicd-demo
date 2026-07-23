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

# ---------------------------------------------------------------------------
# Lazy import of promotion_core — supports both installed-package and
# direct-script execution from the repo root (serverless task)
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

_HANDBOOK_PATH = _REPO_ROOT / "modelops_handbook" / "ml-model-lifecycle.md"


def _load_ml_rules() -> str:
    """Load and parse ML handbook rules from ml-model-lifecycle.md.

    Reads the `### [RULE-ID]` handbook format, parses each block into a compact
    prompt-ready bullet line via promotion_core.parse_handbook_rules(), so the
    rule IDs and citations exactly match the handbook.

    Falls back to the inline DEFAULT_ML_RULES if the file is unreadable.
    """
    if _HANDBOOK_PATH.exists():
        try:
            text = _HANDBOOK_PATH.read_text()
            rules = promotion_core.parse_handbook_rules(text)
            print(f"Loaded and parsed ML rules from {_HANDBOOK_PATH}")
            return rules
        except OSError as e:
            print(f"Could not read handbook file: {e}. Using inline defaults.")
    else:
        print(
            f"Handbook file not found at {_HANDBOOK_PATH}. "
            "Using inline defaults from promotion_core.DEFAULT_ML_RULES."
        )
    return promotion_core.DEFAULT_ML_RULES


def _ensure_experiment_parent(experiment_name: str) -> None:
    """Create the experiment's parent workspace folder if it doesn't exist.

    `mlflow.set_experiment("/ModelOps/...")` fails with NOT_FOUND if the parent directory
    doesn't exist. Idempotent (mkdirs is a no-op if present); best-effort.
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


def _call_llm(system: str, user: str, max_attempts: int = 3) -> str:
    """Call databricks-glm-5-2 with the promotion prompt, retrying empty responses.

    Runs as the CI SP (which owns the model and holds EXECUTE on the FM). Uses the
    serving OpenAI client for consistency with the reviewer agent. GLM-5-2 occasionally
    returns an EMPTY completion; an empty string is unparseable and would make the gate
    default to BLOCK spuriously — so retry a few times and only return what we get.
    """
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient().serving_endpoints.get_open_ai_client()
    last = ""
    for attempt in range(1, max_attempts + 1):
        resp = client.chat.completions.create(
            model=LLM_ENDPOINT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=1200,
            temperature=0.0,
        )
        last = (resp.choices[0].message.content or "").strip()
        if last:
            return last
        print(f"  LLM returned empty response (attempt {attempt}/{max_attempts}) — retrying")
    return last


# ---------------------------------------------------------------------------
# Gate entry point — instrumented with MLflow 3 tracing
# ---------------------------------------------------------------------------


def run_gate() -> None:
    """Run the promotion gate.  Exits 0 on APPROVE, 1 on BLOCK."""
    mlflow.set_registry_uri("databricks-uc")

    experiment_name = os.environ.get(
        "MLFLOW_EXPERIMENT_NAME", "/ModelOps/demand_forecaster_training"
    )
    _ensure_experiment_parent(experiment_name)
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
            # Raise (not sys.exit) — on the serverless notebook wrapper ANY SystemExit is
            # reported as a task failure, so we fail the task by raising, which correctly
            # skips the downstream 'promote' task.
            raise RuntimeError("No @challenger alias found. Run register.py first.")

        # --- Bootstrap check -----------------------------------------------
        bootstrap = promotion_core.bootstrap_decision(champion_exists)
        if bootstrap is not None:
            print("Bootstrap: no champion found — auto-approving.")
            print(f"Justification: {bootstrap['justification']}")
            mlflow.log_param("gate_decision", "APPROVE_BOOTSTRAP")
            # APPROVE → return normally so the 'promote' task runs.
            return

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
                    k: v for k, v in challenger_metrics.items() if k not in ("version", "run_id")
                },
                champion_metrics={
                    k: v for k, v in champion_metrics.items() if k not in ("version", "run_id")
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
        # Return normally → task succeeds → downstream 'promote' runs.
        return
    # BLOCK → raise so the task fails and 'promote' is skipped. On the serverless
    # notebook wrapper, sys.exit(0) would ALSO raise SystemExit and be reported as a
    # failure — so APPROVE must return, and BLOCK must raise a real exception.
    raise RuntimeError(f"Promotion gate BLOCKED — promotion denied. Justification: {justification}")


def main() -> None:
    run_gate()


if __name__ == "__main__":
    main()

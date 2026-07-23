"""Log + register the ModelOps Reviewer (tracer) to Unity Catalog.

Run:  DATABRICKS_AUTH_STORAGE=plaintext python modelops_reviewer/agent/log_model.py
Registers the UC model `...agentic2_mlops_dev.modelops_reviewer` and moves the @prod
alias to the new version. Validates the model loads + predicts locally before deploy.
"""

from __future__ import annotations

import os
import pathlib

import mlflow
from mlflow.models.resources import DatabricksServingEndpoint
from mlflow.tracking import MlflowClient

FULL_NAME = "malcoln_aws_stable_catalog.agentic2_mlops_dev.modelops_reviewer"
EXPERIMENT = "/Users/malcoln.dandaro@databricks.com/modelops_reviewer/experiment"
AGENT_FILE = str(pathlib.Path(__file__).with_name("agent.py"))
CORE_FILE = str(pathlib.Path(__file__).with_name("review_core.py"))
LLM_ENDPOINT = "databricks-glm-5-2"
# KA serving endpoint is auto-named by Agent Bricks (not the display name); overridable.
KA_ENDPOINT = os.environ.get("KA_ENDPOINT", "ka-5f315d3c-endpoint")

mlflow.set_tracking_uri("databricks")  # log to the workspace, not local ./mlruns
mlflow.set_registry_uri("databricks-uc")

# set_experiment fails NOT_FOUND if the parent workspace folder doesn't exist — it does
# not create intermediate dirs. Pre-create it (idempotent, best-effort) so a fresh
# workspace / demo reset doesn't break registration.
try:
    from databricks.sdk import WorkspaceClient

    WorkspaceClient().workspace.mkdirs(EXPERIMENT.rsplit("/", 1)[0])
except Exception as _e:  # noqa: BLE001 — best-effort; set_experiment will report if it matters
    print(f"(experiment parent pre-create skipped: {type(_e).__name__}: {_e})")

mlflow.set_experiment(EXPERIMENT)

# A tiny diff so the input-example validation exercises the real path (retrieval + LLM).
_EXAMPLE = {
    "input": [
        {
            "role": "user",
            "content": "diff --git a/x.py b/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n",
        }
    ]
}

with mlflow.start_run(run_name="grounded"):
    info = mlflow.pyfunc.log_model(
        name="agent",
        python_model=AGENT_FILE,  # "models from code" — agent.py calls set_model()
        code_paths=[CORE_FILE],  # pure cores travel with the model
        input_example=_EXAMPLE,
        pip_requirements=["mlflow==3.12.0", "databricks-sdk", "openai", "pydantic>=2"],
        resources=[  # passthrough auth for the deployed endpoints — DO NOT skip
            DatabricksServingEndpoint(endpoint_name=LLM_ENDPOINT),
            DatabricksServingEndpoint(endpoint_name=KA_ENDPOINT),
        ],
        registered_model_name=FULL_NAME,
    )
print("model_uri:", info.model_uri)

# Pre-deploy validation: load + predict in the current env (catches code errors
# before the ~15-min endpoint deploy).
mlflow.models.predict(
    model_uri=info.model_uri,
    input_data=_EXAMPLE,
    env_manager="local",
)

client = MlflowClient(registry_uri="databricks-uc")
version = max(
    client.search_model_versions(f"name='{FULL_NAME}'"), key=lambda v: int(v.version)
).version
client.set_registered_model_alias(FULL_NAME, "prod", version)
print("registered version:", version, "→ alias @prod")

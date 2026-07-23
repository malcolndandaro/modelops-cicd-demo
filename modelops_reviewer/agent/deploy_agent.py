"""Deploy the ModelOps Reviewer to a Model Serving endpoint.

Run:  DATABRICKS_AUTH_STORAGE=plaintext python modelops_reviewer/agent/deploy_agent.py [VERSION]
First deploy creates the `modelops-reviewer` endpoint (~15 min); a new model version
deploys in place (~minutes — the "config-only redeploy"). VERSION (argv or
$MODELOPS_DEPLOY_VERSION): a numeric token pins that UC model version; anything else
("@prod", "prod", empty) resolves the @prod alias. The DABs `agent_model_version`
variable feeds this for a bundle-driven version bump.
"""

from __future__ import annotations

import os
import sys

import mlflow
from databricks import agents
from mlflow.tracking import MlflowClient

FULL_NAME = "malcoln_aws_stable_catalog.agentic2_mlops_dev.modelops_reviewer"
ENDPOINT = "modelops-reviewer"

mlflow.set_tracking_uri("databricks")  # agents.deploy resolves the logged model via tracking
mlflow.set_registry_uri("databricks-uc")

client = MlflowClient(registry_uri="databricks-uc")
_arg = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MODELOPS_DEPLOY_VERSION", "")).strip()
# A numeric token pins that UC version; anything else ("@prod"/"prod"/"") resolves the
# @prod alias. The DABs job passes "@prod" (non-empty on purpose: an empty bundle var
# serializes to a null Terraform list element → provider panic "parameters[<nil>]...").
version = _arg if _arg.isdigit() else client.get_model_version_by_alias(FULL_NAME, "prod").version
print(f"deploying {FULL_NAME} v{version} → endpoint {ENDPOINT}…")

# The deployed agent calls GLM-5-2 as the CI service principal (which holds EXECUTE on the
# FM under this account's Foundation Model UC permissions feature). Inject its creds as
# served-entity env vars so the agent's _call_llm authenticates as the SP rather than the
# down-scoped OBO token (which lacks USE CATALOG on system). Sourced from the deploy env —
# never hardcoded. Set MODELOPS_SP_CLIENT_ID + MODELOPS_SP_CLIENT_SECRET before running.
_sp_id = os.environ.get("MODELOPS_SP_CLIENT_ID", "")
_sp_secret = os.environ.get("MODELOPS_SP_CLIENT_SECRET", "")
_env_vars = {}
if _sp_id and _sp_secret:
    _env_vars = {"MODELOPS_SP_CLIENT_ID": _sp_id, "MODELOPS_SP_CLIENT_SECRET": _sp_secret}
    print("injecting CI SP creds as served-entity env vars for FM auth")
else:
    print("WARNING: MODELOPS_SP_CLIENT_ID/SECRET not set — agent will use ambient OBO auth "
          "(will 403 on the FM if the FM-UC-permissions feature is enabled).")

deployment = agents.deploy(
    FULL_NAME,
    version,
    endpoint_name=ENDPOINT,
    tags={"project": "modelops-session2"},
    environment_vars=_env_vars,
)
print("endpoint_name:", deployment.endpoint_name)
print("query_endpoint:", deployment.query_endpoint)

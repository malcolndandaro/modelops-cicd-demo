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

try:
    deployment = agents.deploy(
        FULL_NAME,
        version,
        endpoint_name=ENDPOINT,
        tags={"project": "modelops-session2"},
        environment_vars=_env_vars,
    )
    print("endpoint_name:", deployment.endpoint_name)
    print("query_endpoint:", deployment.query_endpoint)
except ValueError as e:
    # agents.deploy refuses to re-deploy a version the endpoint already serves. In that
    # case just push the (possibly new) env vars onto the existing served entity via
    # update_config — this is what makes a demo re-run / env-var change idempotent.
    if "already serves" not in str(e):
        raise
    print(f"version {version} already served — updating env vars via update_config…")
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import Route, ServedEntityInput, TrafficConfig

    se_name = f"malcoln_aws_stable_catalog-agentic2_mlops_dev-modelops_review_{version}"
    base_env = {
        "ENABLE_LANGCHAIN_STREAMING": "true",
        "ENABLE_MLFLOW_TRACING": "true",
        "RETURN_REQUEST_ID_IN_RESPONSE": "true",
    }
    WorkspaceClient().serving_endpoints.update_config(
        name=ENDPOINT,
        served_entities=[
            ServedEntityInput(
                entity_name=FULL_NAME,
                entity_version=str(version),
                name=se_name,
                workload_size="Small",
                scale_to_zero_enabled=False,
                environment_vars={**base_env, **_env_vars},
            )
        ],
        traffic_config=TrafficConfig(routes=[Route(served_model_name=se_name, traffic_percentage=100)]),
    )
    print(f"update_config OK — {ENDPOINT} serves v{version} with FM-auth env vars, 100% traffic")

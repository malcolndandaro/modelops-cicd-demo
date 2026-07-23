"""ModelOps Reviewer — slice 04: real, retrieval-grounded, cited findings.

Imperative shell around the pure cores in review_core.py:
  diff → build_review_context → query Knowledge Assistant (grounding) →
  build_review_prompt → call the foundation model → parse_findings → return.

Output is the Finding contract as JSON (the CI shell, review_pr.py, renders it).
Grounding is provided by the modelops-handbook-ka Knowledge Assistant, which cites
the exact handbook passages and closes the "same knowledge base powers Q&A and
review" loop.
"""

from __future__ import annotations

import json
import os

import mlflow
import review_core
from databricks.sdk import WorkspaceClient
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse

LLM_ENDPOINT = "databricks-glm-5-2"
# The Knowledge Assistant's SERVING endpoint is auto-named by Agent Bricks (e.g.
# "ka-5f315d3c-endpoint"), NOT the KA display name. Overridable via KA_ENDPOINT so a
# demo reset that recreates the KA can repoint the reviewer without a code change.
KA_ENDPOINT = os.environ.get("KA_ENDPOINT", "ka-5f315d3c-endpoint")


def _input_text(req: ResponsesAgentRequest) -> str:
    parts: list[str] = []
    for item in req.input:
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        c = d.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for seg in c:
                if isinstance(seg, dict) and seg.get("text"):
                    parts.append(seg["text"])
    return "\n".join(parts)


def _ka_answer_text(resp: dict) -> str:
    """Extract answer text from a KA response. The Agent Bricks KA endpoint speaks the
    Responses API (output[].content[].text). Also tolerate a chat-completions shape
    (choices[].message.content) so the reviewer survives an endpoint format change."""
    parts: list[str] = []
    # Responses API shape
    for item in resp.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("text"):
                parts.append(c["text"])
            elif isinstance(c, str):
                parts.append(c)
    # Chat-completions fallback
    if not parts:
        for choice in resp.get("choices") or []:
            content = (choice.get("message") or {}).get("content", "")
            if content:
                parts.append(content)
    return "\n".join(parts).strip()


def _query_ka(query_text: str) -> str | None:
    """Query the modelops-handbook-ka Knowledge Assistant for grounding context.

    Returns the cited answer text, or None if the call fails. Retrieval is
    BEST-EFFORT — a failure here must not prevent the review from running.
    """
    try:
        w = WorkspaceClient()
        # KA endpoint uses the Responses API: `input`, NOT `messages`.
        resp = w.api_client.do(
            "POST",
            f"/serving-endpoints/{KA_ENDPOINT}/invocations",
            body={
                "input": [
                    {
                        "role": "user",
                        "content": (
                            "Which ModelOps Handbook rules does this code diff violate? "
                            "Name each rule id and quote its citation. "
                            f"{query_text[:1500]}"
                        ),
                    }
                ]
            },
        )
        text = _ka_answer_text(resp) if isinstance(resp, dict) else ""
        return text or None
    except Exception as e:  # noqa: BLE001 — retrieval is best-effort
        print(f"KA grounding degraded: {type(e).__name__}: {e}")
    return None


def _call_llm(system: str, user: str) -> str:
    """Call the GLM-5-2 FM endpoint via an OpenAI-compatible client over /serving-endpoints.

    Auth: this account has the Foundation Model UC permissions feature enabled, so the
    agent's down-scoped on-behalf-of token does NOT carry `USE CATALOG on system` and 403s.
    We therefore authenticate as the CI service principal (granted EXECUTE on
    system.ai.databricks-glm-5-2), whose client id/secret are injected as env vars on the
    served entity (MODELOPS_SP_CLIENT_ID / MODELOPS_SP_CLIENT_SECRET). When those aren't
    present (e.g. local log_model validation), fall back to ambient auth.
    """
    from databricks.sdk import WorkspaceClient

    sp_id = os.environ.get("MODELOPS_SP_CLIENT_ID")
    sp_secret = os.environ.get("MODELOPS_SP_CLIENT_SECRET")
    if sp_id and sp_secret:
        # CRITICAL: force oauth-m2m. Inside Model Serving the injected OBO token
        # (DATABRICKS_TOKEN) is ALSO present, so without an explicit auth_type the SDK
        # sees two methods and errors ("more than one authorization method configured:
        # oauth and pat") or silently uses the OBO token (which lacks USE CATALOG on
        # system → 403). Pinning oauth-m2m makes it authenticate as the CI SP.
        host = os.environ.get("DATABRICKS_HOST") or WorkspaceClient().config.host
        w = WorkspaceClient(
            host=host, client_id=sp_id, client_secret=sp_secret, auth_type="oauth-m2m"
        )
    else:
        w = WorkspaceClient()  # ambient auth (local validation / creator context)
    client = w.serving_endpoints.get_open_ai_client()
    resp = client.chat.completions.create(
        model=LLM_ENDPOINT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=1800,
        temperature=0.0,
    )
    return resp.choices[0].message.content


class ModelopsReviewer(ResponsesAgent):
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        diff = _input_text(request)
        context = review_core.build_review_context(diff)
        # Query text = the added code itself, so the KA finds rules whose content
        # mentions cross-env refs, .collect(), sys.argv, SQL style, etc.
        query_text = "\n".join(code for f in context["files"] for _, code in f.get("added", []))
        grounding_text = _query_ka(query_text or "coding standards")
        # Pass empty rules list — the KA grounding_text carries the handbook context.
        system, user = review_core.build_review_prompt(context, [], grounding_text=grounding_text)
        raw = _call_llm(system, user)
        payload = review_core.parse_review(raw)  # tolerant: recovers summary + findings together
        return ResponsesAgentResponse(
            output=[
                self.create_text_output_item(
                    text=json.dumps(payload, ensure_ascii=False), id="modelops_review_1"
                )
            ]
        )


mlflow.models.set_model(ModelopsReviewer())

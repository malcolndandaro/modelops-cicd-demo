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
    """Call the GLM-5-2 FM endpoint using the OpenAI client over /serving-endpoints.

    This is the documented pattern for calling an FM from INSIDE a deployed agent: it
    uses the Model-Serving-injected on-behalf-of token (DATABRICKS_TOKEN/HOST), which the
    `resources=[DatabricksServingEndpoint(LLM_ENDPOINT)]` passthrough authorizes. The
    older mlflow.deployments get_deploy_client path re-resolved through the `system`
    catalog and 403'd ("USE CATALOG on system") for the serving identity.
    """
    from databricks.sdk import WorkspaceClient

    # Use the SDK's OpenAI-compatible client: it resolves auth from the ambient context —
    # the injected on-behalf-of token when running inside Model Serving, or the local
    # profile (OAuth/PAT) during log_model validation. Avoids the static-api_key problem
    # of constructing openai.OpenAI directly, and the `system` catalog 403 of the older
    # mlflow.deployments path.
    client = WorkspaceClient().serving_endpoints.get_open_ai_client()
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

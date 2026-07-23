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
from mlflow.deployments import get_deploy_client
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


def _query_ka(query_text: str) -> str | None:
    """Query the modelops-handbook-ka Knowledge Assistant for grounding context.

    Returns the cited answer text, or None if the call fails. Retrieval is
    BEST-EFFORT — a failure here must not prevent the review from running.
    """
    try:
        w = WorkspaceClient()
        resp = w.api_client.do(
            "POST",
            f"/serving-endpoints/{KA_ENDPOINT}/invocations",
            body={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Which ModelOps Handbook rules does this code diff violate? "
                            f"{query_text[:1500]}"
                        ),
                    }
                ]
            },
        )
        # KA returns a chat-completion style response with cited answer text.
        for choice in (resp.get("choices") or []):
            msg = (choice.get("message") or {})
            text = msg.get("content", "")
            if text.strip():
                return text.strip()
    except Exception as e:  # noqa: BLE001 — retrieval is best-effort
        print(f"KA grounding degraded: {type(e).__name__}: {e}")
    return None


def _call_llm(system: str, user: str) -> str:
    client = get_deploy_client("databricks")
    resp = client.predict(
        endpoint=LLM_ENDPOINT,
        inputs={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1800,
            # NOTE: opus-4-8 rejects the `temperature` parameter (400 BAD_REQUEST) — it
            # manages sampling internally. Do not re-add it for this model.
        },
    )
    return resp["choices"][0]["message"]["content"]


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

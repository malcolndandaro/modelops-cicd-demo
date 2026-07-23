"""Pure, deterministic cores for the ModelOps Promotion Gate (Gate 2).

No I/O, no SDK calls, no network — fully unit-testable with plain data.
The imperative shell (promotion_gate.py) imports these; the MlflowClient reads,
LLM call, and MLflow tracing live there.

Five cores:
  - parse_handbook_rules(text)
      → compact rule string parsed from the `### [RULE-ID]` handbook format
  - build_promotion_prompt(challenger_metrics, champion_metrics, config_diff, ml_rules)
      → (system, user) prompt strings
  - parse_decision(raw)
      → {"decision": "APPROVE"|"BLOCK", "findings": [...], "justification": "..."}
  - bootstrap_decision(champion_exists)
      → APPROVE when no champion exists yet (first-run bootstrap)
  - compare_metrics(challenger_mae, champion_mae)
      → {"better": bool, "delta": float, "summary": str}

Contract: decision is always "APPROVE" or "BLOCK", never a third value.
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# ML handbook rules injected into the promotion prompt
# ---------------------------------------------------------------------------

# These are the default inline rules injected when the handbook file cannot be read.
# The imperative shell (promotion_gate.py) tries to load ml-model-lifecycle.md first.
# TODO: read rules from modelops_handbook/ml-model-lifecycle.md once that file is added
#       by the handbook teammate.  See: .scratch/modelops-cicd-demo/issues/0001-spec.md
DEFAULT_ML_RULES = """
- ML-01 [BLOCKER] UC registry only: All model versions MUST be registered to Unity Catalog.
  Workspace registry (deprecated stages Staging/Production) must not be used.
  Promotion is performed by moving the @champion alias, not by transitioning stages.

- ML-02 [BLOCKER] Config + test sync: Any hyperparameter or feature-list change MUST be
  accompanied in the same PR by an updated max_acceptable_mae in config.yml AND an updated
  metric-regression test in tests/test_demand_forecaster.py.

- ML-03 [BLOCKER] Challenger must not regress champion: The challenger's MAE must be <= the
  champion's MAE, or the degradation must be explicitly justified and approved by a human
  reviewer. Gate 2 enforces this automatically; unjustified regression is a BLOCK.

- ML-04 [BLOCKER] No cross-env config references: Training config and job definitions must
  reference only the target environment's catalog/schema.  A dev config pointing to
  agentic2_mlops_prod (or mlops_prod) is an automatic BLOCK.

- ML-05 [SUGGESTION] Determinism: training must use a fixed random_state for reproducibility.
  Non-deterministic runs make metric comparisons meaningless.

- ML-06 [SUGGESTION] Metric thresholds must be conservative: max_acceptable_mae should have
  a buffer above the expected MAE to avoid flaky tests on small data variance.
""".strip()


# ---------------------------------------------------------------------------
# Core 1: build promotion prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are the ModelOps Promotion Gate — an AI that decides whether a challenger ML model "
    "should replace the current champion in Unity Catalog. "
    "You evaluate based ONLY on the ML rules provided. Do not invent rules. "
    "Every finding MUST reference one of the supplied rule IDs (ML-01 through ML-06 or similar). "
    "Be objective and concise. Lower MAE is better (less forecast error). "
    "If no champion exists, respond APPROVE — this is the first deployment (bootstrap). "
    "Respond ONLY with valid JSON matching this exact schema:\n"
    '{"decision": "APPROVE" | "BLOCK", '
    '"findings": [{"rule_id": "<id>", "severity": "BLOCKER|SUGGESTION", '
    '"message": "<what was found>"}], '
    '"justification": "<one paragraph explaining the decision>"}'
)


def build_promotion_prompt(
    challenger_metrics: dict,
    champion_metrics: dict | None,
    config_diff: str,
    ml_rules: str | None = None,
) -> tuple[str, str]:
    """Build the (system, user) prompt for the LLM promotion decision.

    Args:
        challenger_metrics: dict of metric_name -> value for the challenger version.
        champion_metrics: dict of metric_name -> value for the current champion, or
                          None/empty if no champion exists yet (bootstrap scenario).
        config_diff: text diff of config.yml between the challenger run and the
                     champion run (or "(no champion — first deployment)" if bootstrap).
        ml_rules: ML handbook rules text to inject.  Defaults to DEFAULT_ML_RULES.

    Returns:
        (system_prompt, user_prompt) tuple.
    """
    rules_block = (ml_rules or DEFAULT_ML_RULES).strip()

    if not champion_metrics:
        champion_block = "(no current champion — this is the first deployment)"
    else:
        champion_block = "\n".join(f"  {k}: {v}" for k, v in sorted(champion_metrics.items()))

    challenger_block = "\n".join(f"  {k}: {v}" for k, v in sorted(challenger_metrics.items()))

    user = (
        "ML HANDBOOK RULES (cite ONLY these rule IDs):\n"
        f"{rules_block}\n\n"
        "CHAMPION METRICS:\n"
        f"{champion_block}\n\n"
        "CHALLENGER METRICS:\n"
        f"{challenger_block}\n\n"
        "CONFIG DIFF (challenger vs champion):\n"
        f"{config_diff or '(no config changes detected)'}\n\n"
        "Based on the metrics and config diff, should the challenger replace the champion? "
        "Return the JSON decision."
    )
    return _SYSTEM, user


# ---------------------------------------------------------------------------
# Core 2: parse LLM decision — defensive, fence-tolerant
# ---------------------------------------------------------------------------

_VALID_DECISIONS = frozenset({"APPROVE", "BLOCK"})


def _first_balanced_object(s: str) -> str | None:
    """Return the first brace-balanced {...} substring (string/escape aware).

    Reuses the approach from review_core.loads_tolerant to handle models that
    wrap JSON in prose or ```json fences.
    """
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _strip_fences(raw: str) -> str:
    """Remove leading/trailing ```json ... ``` or ``` ... ``` fences."""
    raw = raw.strip()
    raw = re.sub(r"^```[a-zA-Z0-9_+.-]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _close_json(prefix: str) -> str | None:
    """Given a prefix of a JSON object, append the minimal closers to balance it.

    Closes an open string, drops a dangling trailing comma / `"key":` fragment, and
    appends the `]`/`}` needed to balance the bracket stack. Returns the candidate or None.
    """
    stack: list[str] = []
    in_str = esc = False
    for ch in prefix:
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    out = prefix
    if in_str:
        out += '"'
    out = out.rstrip()
    # a trailing `,` or a dangling `"key":` (value never arrived) can't be closed — trim it
    out = re.sub(r",\s*$", "", out)
    out = re.sub(r'"[^"]*"\s*:\s*$', "", out).rstrip().rstrip(",")
    return out + "".join(reversed(stack)) if stack or out.endswith("}") else None


def _repair_truncated_json(s: str) -> str | None:
    """Best-effort recovery of JSON truncated mid-object (LLM token limit).

    Brute-force but robust: from the full string down to the opening brace, try closing
    each prefix and json.loads it; return the LARGEST prefix that parses to a dict with a
    "decision" key. So a cut-off `{"decision":"BLOCK","findings":[{"rule_id":"ML-03",...<cut>`
    recovers the decision plus every COMPLETE finding, dropping only the incomplete tail.
    """
    start = s.find("{")
    if start < 0:
        return None
    body = s[start:]
    # Walk end→start; first (largest) prefix that closes into a valid dict wins.
    for end in range(len(body), 1, -1):
        candidate = _close_json(body[:end])
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and "decision" in obj:
            return candidate
    return None


def _loads_tolerant(raw: object) -> object | None:
    """Best-effort JSON decode tolerant of fences, trailing prose, AND truncation."""
    if isinstance(raw, dict | list):
        return raw
    if not isinstance(raw, str):
        return None
    # Try direct parse first
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        pass
    # Fall back to balanced-brace extraction from the original string
    obj_str = _first_balanced_object(raw)
    if obj_str is not None:
        try:
            return json.loads(obj_str)
        except (ValueError, TypeError):
            pass
    # Last resort: the JSON was truncated mid-object (LLM token limit) so no balanced
    # object exists — repair it by auto-closing brackets so the decision survives.
    repaired = _repair_truncated_json(cleaned)
    if repaired is None:
        return None
    try:
        return json.loads(repaired)
    except (ValueError, TypeError):
        return None


def parse_decision(raw: object) -> dict:
    """Parse the LLM's raw output into a structured promotion decision.

    Contract:
        - "decision" is always "APPROVE" or "BLOCK" (never None, never a third value).
        - "findings" is always a list (may be empty).
        - "justification" is always a string.
        - Any unparseable or missing decision defaults to BLOCK (fail-safe).

    Never raises.
    """
    data = _loads_tolerant(raw)
    if not isinstance(data, dict):
        return {
            "decision": "BLOCK",
            "findings": [],
            "justification": (
                f"Gate failed to parse a valid decision from the LLM response. "
                f"Raw output: {str(raw)[:500]}"
            ),
        }

    raw_decision = str(data.get("decision", "")).strip().upper()
    decision = raw_decision if raw_decision in _VALID_DECISIONS else "BLOCK"

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        findings = []
    # Coerce each finding to a safe dict
    clean_findings = []
    for f in findings:
        if isinstance(f, dict):
            clean_findings.append(
                {
                    "rule_id": str(f.get("rule_id", "UNKNOWN")),
                    "severity": str(f.get("severity", "SUGGESTION")).upper(),
                    "message": str(f.get("message", "")),
                }
            )

    justification = str(data.get("justification", "")).strip()
    if not justification:
        justification = f"Decision: {decision} (no justification provided by the LLM)."

    return {
        "decision": decision,
        "findings": clean_findings,
        "justification": justification,
    }


# ---------------------------------------------------------------------------
# Core 3: bootstrap decision
# ---------------------------------------------------------------------------


def bootstrap_decision(champion_exists: bool) -> dict | None:
    """Return an auto-APPROVE decision when no champion exists, else None.

    The caller uses this to skip the LLM call on the very first deployment.
    Returning None means 'not a bootstrap situation — run the gate normally'.
    """
    if champion_exists:
        return None
    return {
        "decision": "APPROVE",
        "findings": [],
        "justification": (
            "Bootstrap: no current @champion exists. "
            "Auto-approving to establish the first champion version. "
            "Future promotions will require challenger metrics to match or beat the champion."
        ),
    }


# ---------------------------------------------------------------------------
# Core 4: handbook parser — convert handbook markdown to compact rule lines
# ---------------------------------------------------------------------------

# Matches the handbook's ### [RULE-ID] heading format
_RULE_HEADING = re.compile(r"^###\s+\[(?P<rule_id>[A-Z]+-\d+)\]\s+(?P<title>.+)$")
_SEVERITY_LINE = re.compile(r"\*\*Severity:\*\*\s*(?P<severity>BLOCKER|SUGGESTION|STYLE)")
_CITATION_LINE = re.compile(r"\*\*Citation:\*\*\s*(?P<citation>.+)")


def parse_handbook_rules(text: str) -> str:
    """Parse a handbook markdown file into compact prompt-ready rule lines.

    Reads the `### [RULE-ID] Title` / `**Severity:**` / `**Citation:**` structure
    from modelops_handbook/ml-model-lifecycle.md (and any file sharing that format)
    and converts each rule block into a single compact line:

        - ML-01 [BLOCKER] (Citation: ModelOps Handbook › ML Model Lifecycle › ML-01):
          A hyperparameter or feature change requires updating the metric-regression test ...

    Strips the ❌/✅ example lines to keep the prompt concise.  Falls back to
    DEFAULT_ML_RULES (returned unchanged) if `text` contains no rule headings.
    """
    rules: list[str] = []
    lines = (text or "").splitlines()

    cur_id: str | None = None
    cur_title: str | None = None
    cur_severity: str = "SUGGESTION"
    cur_citation: str = ""
    cur_body: list[str] = []

    def _flush() -> None:
        if cur_id is None:
            return
        body = " ".join(
            ln.strip()
            for ln in cur_body
            if ln.strip()
            and not ln.strip().startswith("❌")
            and not ln.strip().startswith("✅")
            and not ln.strip().startswith("-")  # skip sub-bullets
            and "**Severity:**" not in ln
            and "**Citation:**" not in ln
        )
        # Use title as body if body is empty after filtering
        body = body.strip() or (cur_title or "")
        citation = cur_citation.strip() or f"ModelOps Handbook › ML Model Lifecycle › {cur_id}"
        rules.append(f"- {cur_id} [{cur_severity}] (Citation: {citation}): {body[:400]}")

    for line in lines:
        m_heading = _RULE_HEADING.match(line)
        if m_heading:
            _flush()
            cur_id = m_heading.group("rule_id")
            cur_title = m_heading.group("title").strip()
            cur_severity = "SUGGESTION"
            cur_citation = ""
            cur_body = []
            continue

        if cur_id is None:
            continue

        m_sev = _SEVERITY_LINE.search(line)
        if m_sev:
            cur_severity = m_sev.group("severity")
            continue

        m_cit = _CITATION_LINE.search(line)
        if m_cit:
            cur_citation = m_cit.group("citation")
            continue

        cur_body.append(line)

    _flush()  # flush last rule

    if not rules:
        return DEFAULT_ML_RULES

    return "\n".join(rules)


# ---------------------------------------------------------------------------
# Core 5: metric comparison
# ---------------------------------------------------------------------------


def compare_metrics(challenger_mae: float, champion_mae: float) -> dict:
    """Compare challenger vs champion MAE. Lower MAE is better.

    Returns:
        {
          "better": bool,          # True if challenger MAE <= champion MAE
          "delta": float,          # challenger_mae - champion_mae (negative = improvement)
          "pct_change": float,     # relative change in percent
          "summary": str,          # human-readable one-liner
        }
    """
    delta = challenger_mae - champion_mae
    pct = (delta / champion_mae * 100) if champion_mae != 0 else 0.0
    better = challenger_mae <= champion_mae

    if better:
        direction = f"improved by {abs(delta):.4f} ({abs(pct):.1f}%)"
    else:
        direction = f"degraded by {delta:.4f} ({pct:.1f}%) — BLOCKER unless justified"

    summary = (
        f"Challenger MAE: {challenger_mae:.4f} vs Champion MAE: {champion_mae:.4f} — "
        f"{direction}"
    )
    return {
        "better": better,
        "delta": delta,
        "pct_change": pct,
        "summary": summary,
    }

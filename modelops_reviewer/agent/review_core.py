"""Pure, deterministic cores for the ModelOps Reviewer (slice 04).

No I/O, no SDK calls, no network — everything here is unit-testable with plain
data. The agent (agent.py) and the CI shell (review_pr.py) import these; the
Vector Search query and the foundation-model call live in the agent shell.

Three cores:
  - build_review_context(diff)   parse a unified diff → structured context
  - build_review_prompt(ctx, rules)  assemble the system/user prompt
  - parse_findings(raw)          validate model output → list[Finding]
"""

from __future__ import annotations

import json
import re

# --- Finding contract (mirrors CONTEXT.md / PRD) ---------------------------------
SEVERITIES = ("BLOCKER", "SUGGESTION", "STYLE")
REQUIRED_FIELDS = ("file", "severity", "rule_id", "citation", "message")

_LANG_BY_EXT = {
    ".py": "python",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sh": "shell",
}


def detect_language(path: str) -> str:
    for ext, lang in _LANG_BY_EXT.items():
        if path.endswith(ext):
            return lang
    return "text"


# --- Core 1: diff → review context -----------------------------------------------
_DIFF_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")


def build_review_context(diff: str) -> dict:
    """Parse a `git diff` into per-file added lines with their new line numbers.

    Returns {"files": [{path, language, is_binary, is_rename, added:[(lineno, text)],
    hunks: str}], "n_files": int}. Robust to empty diffs, binary files, and renames.
    """
    files: list[dict] = []
    cur: dict | None = None
    new_lineno = 0
    for line in (diff or "").splitlines():
        m = _DIFF_HEADER.match(line)
        if m:
            cur = {
                "path": m.group("b"),
                "language": detect_language(m.group("b")),
                "is_binary": False,
                "is_rename": False,
                "added": [],
                "hunks": [],
            }
            files.append(cur)
            new_lineno = 0
            continue
        if cur is None:
            continue
        if line.startswith("Binary files"):
            cur["is_binary"] = True
        elif line.startswith("rename from") or line.startswith("rename to"):
            cur["is_rename"] = True
        elif line.startswith("+++ b/"):
            cur["path"] = line[6:].rstrip()  # git may pad the path with a tab
            cur["language"] = detect_language(cur["path"])
        else:
            hm = _HUNK.match(line)
            if hm:
                new_lineno = int(hm.group("start"))
                cur["hunks"].append(line)
            elif line.startswith("+") and not line.startswith("+++"):
                cur["added"].append((new_lineno, line[1:]))
                new_lineno += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass  # removed line — does not advance the new-file counter
            elif not line.startswith("\\"):  # context line
                if new_lineno:
                    new_lineno += 1
    for f in files:
        f["hunks"] = "\n".join(f["hunks"])
    return {"files": files, "n_files": len(files)}


# --- Core 2: prompt assembly -----------------------------------------------------
_SYSTEM = (
    "You are the ModelOps Reviewer, an automated code reviewer for ModelOps. "
    "You review a PR diff ONLY against the ModelOps Handbook rules provided. "
    "Do not invent rules. Each finding MUST cite a rule_id from the provided list. "
    "Respond in English. If there are no violations, return an empty findings list.\n\n"
    "Deterministic linters ALREADY run on every PR and cover syntax/style/security-lint: "
    "Ruff (Python: E/F/I/B/UP/SIM/S) and sqlfluff (SQL), plus `databricks bundle validate`. "
    "DO NOT duplicate their findings. Focus on the SEMANTIC/policy layer of the Handbook "
    "that they CANNOT detect (cross-env, Transform pattern, secrets, naming, DABs).\n\n"
    "Severity: use the severity_hint from the rule, but ESCALATE to BLOCKER any "
    "reference to another environment's catalog (e.g. *_prd / prod from dev) or a "
    "secret/credential in code. STYLE for formatting nits.\n\n"
    "Return ONLY valid JSON, with no extra text, in this exact form:\n"
    '{"summary": "<one-line summary>", "findings": [{'
    '"file": "<path>", "line": <integer or null>, "severity": "BLOCKER|SUGGESTION|STYLE", '
    '"rule_id": "<id from the list>", "citation": "<rule citation>", '
    '"message": "<what is wrong>", "suggestion": "<how to fix it or null>"}]}'
)


def build_review_prompt(
    context: dict, rules: list[dict], grounding_text: str | None = None
) -> tuple[str, str]:
    """Return (system, user) messages.

    `rules` are retrieved handbook rows (structured list). `grounding_text` is an
    optional free-text grounding block from the Knowledge Assistant — if provided it
    is appended after the structured rules block so the model gets both signals.
    """
    rules_block = (
        "\n".join(
            f"- {r.get('rule_id')} [{r.get('severity_hint', 'SUGGESTION')}] "
            f"(citation: {r.get('citation')}): {r.get('content', r.get('title', '')).strip()[:400]}"
            for r in rules
        )
        or "(no rules retrieved)"
    )

    if grounding_text:
        rules_block = rules_block + "\n\nKNOWLEDGE ASSISTANT GROUNDING:\n" + grounding_text.strip()

    files_block = []
    for f in context.get("files", []):
        if f.get("is_binary"):
            files_block.append(f"### {f['path']} (binary — skip)")
            continue
        added = "\n".join(f"  L{ln}: {code}" for ln, code in f.get("added", [])[:200])
        files_block.append(f"### {f['path']} ({f['language']})\n{added}")
    files_text = "\n\n".join(files_block) or "(empty diff)"

    user = (
        "HANDBOOK RULES (cite ONLY these rule_id values):\n"
        f"{rules_block}\n\n"
        "LINES ADDED IN THE PR (use the Lxx number as `line`):\n"
        f"{files_text}\n\n"
        "Return the findings JSON."
    )
    return _SYSTEM, user


# --- Core 3: parse + validate model output → findings ----------------------------
def _coerce_finding(obj: object) -> dict | None:
    if not isinstance(obj, dict):
        return None
    if not all(obj.get(k) not in (None, "") for k in REQUIRED_FIELDS):
        return None
    sev = str(obj["severity"]).upper()
    if sev not in SEVERITIES:
        return None
    line = obj.get("line")
    if isinstance(line, str) and line.isdigit():
        line = int(line)
    if not isinstance(line, int):
        line = None
    return {
        "file": str(obj["file"]),
        "line": line,
        "severity": sev,
        "rule_id": str(obj["rule_id"]),
        "citation": str(obj["citation"]),
        "message": str(obj["message"]),
        "suggestion": (str(obj["suggestion"]) if obj.get("suggestion") else None),
        "patch": (str(obj["patch"]) if obj.get("patch") else None),
    }


def _first_balanced_object(s: str) -> str | None:
    """Return the first brace-balanced {...} substring (string/escape aware).

    Used to recover JSON from models that wrap it in prose or code fences —
    without the greedy `\\{.*\\}` bug that spans trailing junk and breaks parsing.
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


def loads_tolerant(raw: object) -> object | None:
    """Best-effort JSON decode. Returns the parsed value, or None on failure."""
    if isinstance(raw, dict | list):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        obj = _first_balanced_object(raw)
        if obj is None:
            return None
        try:
            return json.loads(obj)
        except (ValueError, TypeError):
            return None


def parse_findings(raw: object) -> list[dict]:
    """Validate model output → list of Finding dicts. Never raises.

    Accepts a JSON string, a dict (`{"findings": [...]}`), or a list. Malformed
    input or any parse error → [] (the agent stays non-crashing; user story 38).
    """
    data = loads_tolerant(raw)
    if isinstance(data, dict):
        items = data.get("findings", [])
    elif isinstance(data, list):
        items = data
    else:
        return []
    if not isinstance(items, list):
        return []
    return [f for it in items if (f := _coerce_finding(it)) is not None]


def parse_review(raw: object) -> dict:
    """Parse model output into {"summary": str, "findings": [Finding]} tolerantly.

    Single source of truth so the agent and CI never diverge on how output is read
    (the summary is recovered with the same fence-tolerant decode as findings).
    """
    data = loads_tolerant(raw)
    summary = data.get("summary", "") if isinstance(data, dict) else ""
    return {"summary": str(summary or ""), "findings": parse_findings(data)}


# --- Core 4: severity gate + GitHub Check Run mapper (slice 05) -------------------
# GitHub Checks API: max 50 annotations per request; levels are notice/warning/failure.
MAX_ANNOTATIONS = 50
_ANNOTATION_LEVEL = {"BLOCKER": "failure", "SUGGESTION": "warning", "STYLE": "notice"}


def decide_gate(findings: list[dict]) -> dict:
    """Severity gate (ADR-0002): any BLOCKER → failure; only SUGGESTION/STYLE →
    neutral; no findings → success. Returns the GateDecision contract.
    """
    valid = [f for f in (findings or []) if isinstance(f, dict) and f.get("severity") in SEVERITIES]
    n_block = sum(1 for f in valid if f["severity"] == "BLOCKER")
    n = len(valid)
    if n == 0:
        return {
            "conclusion": "success",
            "blocker_count": 0,
            "summary": "✅ No findings against the ModelOps Handbook.",
        }
    if n_block:
        return {
            "conclusion": "failure",
            "blocker_count": n_block,
            "summary": (
                f"🔴 {n_block} of {n} finding(s) are BLOCKER — merge blocked until resolved."
            ),
        }
    return {
        "conclusion": "neutral",
        "blocker_count": 0,
        "summary": f"🟡 {n} advisory finding(s) — do not block merge.",
    }


def to_check_run(findings: list[dict], decision: dict) -> dict:
    """Map findings → a GitHub Check Run payload (conclusion + output.annotations).

    Line/file-level annotations (file-level uses line 1), severity → annotation
    level, capped at 50 with a Spanish overflow note. Pure — the CI shell posts it.
    """
    annotations = []
    for f in findings or []:
        if not (isinstance(f, dict) and f.get("file") and f.get("severity") in _ANNOTATION_LEVEL):
            continue
        line = f.get("line") if isinstance(f.get("line"), int) and f["line"] >= 1 else 1
        msg = str(f.get("message", "")).strip()
        if f.get("suggestion"):
            msg += f"\n\nSuggestion: {f['suggestion']}"
        if f.get("citation"):
            msg += f"\n\n📖 {f['citation']}"
        annotations.append(
            {
                "path": str(f["file"]),
                "start_line": line,
                "end_line": line,
                "annotation_level": _ANNOTATION_LEVEL[f["severity"]],
                # GitHub limits: title ≤ 255 chars, message ≤ 64KB (else 422s the whole run)
                "title": f"{f['severity']} · {f.get('rule_id', '')}".strip(" ·")[:255],
                "message": (msg or f["severity"])[:65000],
            }
        )
    summary = decision.get("summary", "")
    if len(annotations) > MAX_ANNOTATIONS:
        extra = len(annotations) - MAX_ANNOTATIONS
        annotations = annotations[:MAX_ANNOTATIONS]
        summary += f"\n\n_(+{extra} additional finding(s) not annotated; GitHub's limit is 50.)_"
    titles = {
        "failure": "ModelOps Reviewer — BLOCKER",
        "neutral": "ModelOps Reviewer — suggestions",
        "success": "ModelOps Reviewer — OK",
    }
    return {
        "conclusion": decision.get("conclusion", "neutral"),
        "output": {
            "title": titles.get(decision.get("conclusion"), "ModelOps Reviewer"),
            "summary": summary,
            "annotations": annotations,
        },
    }


# --- Core 5: fix mode (slice 06) -------------------------------------------------
# The fix shell asks the FM for the COMPLETE corrected file (robust vs fragile
# unified-diff application), then validates it parses before the bot pushes.
_WRITE_PERMS = ("write", "maintain", "admin")
_FIX_SYSTEM = (
    "You are the ModelOps Reviewer in FIX MODE. You receive the COMPLETE content of a "
    "file, the relevant ModelOps Handbook RULES, and a list of findings. "
    "Return the COMPLETE corrected file that: "
    "(1) resolves the findings FOLLOWING the ModelOps Handbook conventions; "
    "(2) does NOT introduce new Handbook violations; "
    "(3) PASSES the deterministic linters — Ruff in Python (E/F/I/B/UP/SIM/S: imports on "
    "separate lines and all used, `is None` instead of `== None`, no bare `except:`, "
    "no mutable defaults, f-strings instead of .format, etc.) and sqlfluff in SQL (keywords "
    "in UPPERCASE, aliases with AS, no reserved word identifiers); and "
    "(4) preserves the rest of the code and its behavior. "
    "Do not explain anything: return ONLY the corrected file inside a single "
    "```...``` block (no text outside the block)."
)
_FIX_RETRY_SYSTEM = (
    "You are the ModelOps Reviewer in FIX MODE (RETRY). Your previous attempt to fix "
    "a file FAILED the linter. Fix EXACTLY those linter errors WITHOUT reintroducing "
    "ModelOps Handbook violations or changing behavior. Return ONLY the COMPLETE corrected "
    "file inside a single ```...``` block (no text outside the block)."
)
_FENCE = re.compile(r"```[a-zA-Z0-9_+.-]*\n(?P<code>.*?)```", re.S)


def is_authorized(permission: str, branch_is_protected: bool) -> tuple[bool, str]:
    """ADR-0003 authz: only write/maintain/admin collaborators may trigger a fix,
    and never on a protected branch. `permission` is the GitHub collaborator role.
    """
    if branch_is_protected:
        return False, "The target branch is protected; the bot does not write to protected branches."  # noqa: E501
    if permission not in _WRITE_PERMS:
        return False, f"Insufficient permission ('{permission}'); write/maintain/admin is required."  # noqa: E501
    return True, ""


def build_fix_prompt(
    path: str, original: str, findings: list[dict], rules: list[dict] | None = None
) -> tuple[str, str]:
    issues = (
        "\n".join(
            f"- L{f.get('line')}: [{f.get('severity')}] {f.get('rule_id')} — {f.get('message')}"
            + (f" (suggestion: {f['suggestion']})" if f.get("suggestion") else "")
            for f in findings
        )
        or "(no findings)"
    )
    rules_block = (
        "\n".join(
            f"- {r.get('rule_id')} ({r.get('citation')}): "
            f"{(r.get('content') or r.get('title') or '').strip()[:400]}"
            for r in (rules or [])
        )
        or "(no additional rules — follow those cited in the findings)"
    )
    user = (
        f"FILE: {path}\n\nRELEVANT MODELOPS HANDBOOK RULES:\n{rules_block}\n\n"
        f"FINDINGS TO FIX:\n{issues}\n\n"
        f"CURRENT CONTENT:\n```\n{original}\n```\n\n"
        "Return the COMPLETE corrected file (following the Handbook and passing the "
        "Ruff/sqlfluff linters) in a single code block."
    )
    return _FIX_SYSTEM, user


def build_fix_retry_prompt(path: str, attempted: str, lint_output: str) -> tuple[str, str]:
    """Pure: build the (system, user) for a second fix attempt after the first failed
    the linter. `lint_output` is the raw Ruff/sqlfluff output from the shell."""
    user = (
        f"FILE: {path}\n\nYour previous attempt FAILED the linter with these errors:\n"
        f"{(lint_output or '').strip()[:2000]}\n\n"
        f"ATTEMPT CONTENT:\n```\n{attempted}\n```\n\n"
        "Return the COMPLETE corrected file (without those linter errors and without violating "
        "the Handbook) in a single code block."
    )
    return _FIX_RETRY_SYSTEM, user


def linter_for(path: str) -> str | None:
    """Pure: which deterministic linter guards this file type. The fix shell runs it on
    the generated fix so the bot never pushes lint-failing code. None = no lint gate."""
    if path.endswith(".py"):
        return "ruff"
    if path.endswith(".sql"):
        return "sqlfluff"
    return None


def extract_code(model_output: str) -> str | None:
    """Pull the corrected file content out of the model's fenced code block.

    Requires a ```fenced``` block — prose without a fence is treated as malformed
    (returns None) so the bot never pushes raw model chatter as file content.
    """
    if not isinstance(model_output, str):
        return None
    m = _FENCE.search(model_output)
    if not m:
        return None
    code = m.group("code").rstrip("\n")
    return (code + "\n") if code.strip() else None


def select_fixable(findings: list[dict], changed_files: set[str]) -> dict[str, list[dict]]:
    """Group findings by file, CONFINED to the PR's changed files.

    Security: finding `file` paths come from (untrusted) model output, so the bot
    must never rewrite a path the PR didn't touch. Also rejects absolute or
    parent-escaping paths.
    """
    by_file: dict[str, list[dict]] = {}
    for f in findings or []:
        path = f.get("file") if isinstance(f, dict) else None
        if not path or path.startswith("/") or ".." in path or path not in changed_files:
            continue
        by_file.setdefault(path, []).append(f)
    return by_file


def validate_content(path: str, content: str | None) -> tuple[bool, str]:
    """Deterministic post-fix validation: the corrected file must still parse."""
    if not content or not content.strip():
        return False, "empty content"
    if path.endswith(".py"):
        try:
            compile(content, path, "exec")
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"
    elif path.endswith((".yml", ".yaml")):
        try:
            import yaml

            yaml.safe_load(content)
        except ImportError:
            pass  # no yaml on the runner — skip (non-empty already checked)
        except Exception as e:  # noqa: BLE001 — any parse error = invalid YAML
            return False, f"Invalid YAML: {e}"
    return True, ""


# --- Core 6: eval scorer decisions (slice 09) — pure, unit-testable --------------
def has_rule(findings: list[dict], rule_id: str) -> bool:
    return any(isinstance(f, dict) and f.get("rule_id") == rule_id for f in (findings or []))


def has_rule_prefix(findings: list[dict], prefix: str) -> bool:
    return any(
        isinstance(f, dict) and str(f.get("rule_id", "")).startswith(prefix)
        for f in (findings or [])
    )


def score_cross_env(findings: list[dict], expected: bool) -> bool:
    """Caught-cross-env: ENV-01 presence must match the expectation."""
    return has_rule(findings, "ENV-01") == bool(expected)


def score_transform(findings: list[dict], expected: bool) -> bool:
    """Flagged-transform: a TP-* finding's presence must match the expectation."""
    return has_rule_prefix(findings, "TP-") == bool(expected)


def score_no_false_positives(findings: list[dict], is_clean: bool) -> bool:
    """Zero-false-positives: on clean code, require no findings; else not applicable."""
    if not is_clean:
        return True
    return len(findings or []) == 0

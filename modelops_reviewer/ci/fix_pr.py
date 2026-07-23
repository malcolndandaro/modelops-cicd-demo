"""CI fix-mode: /modelops-fix → generate + validate fixes → open a fix PR.

Triggered by an `issue_comment` containing `/modelops-fix` (production) or by
`workflow_dispatch` (testing). Flow:
  1. authorize the actor (ADR-0003: write/maintain/admin, never a protected branch);
  2. re-review the PR to get findings, grouped by file;
  3. ask the FM for the COMPLETE corrected file per finding-bearing file;
  4. validate each parses (compile/yaml) — abort the whole push if any is invalid;
  5. the ModelOps Bot creates a new branch `modelops-fix/pr-<PR>-<short-run-id>`,
     commits the fixes there, pushes it, then opens a NEW pull request against the
     original PR's head branch, and comments on the original PR with a link to the fix PR.
Never hard-fails the job (exits 0); posts a comment with the outcome.

Bot identity is a GitHub App (ADR-0003): the workflow mints a short-lived installation
token via actions/create-github-app-token (App id in vars.MODELOPS_BOT_APP_ID, key in
secrets.MODELOPS_BOT_APP_PRIVATE_KEY) and passes it as BOT_TOKEN. Because it is not the
GITHUB_TOKEN, the bot's push re-triggers review + checks.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import subprocess  # noqa: S404 — git CLI is required for the commit/push
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "agent"))
import review_core  # noqa: E402 — sibling agent module; needs the sys.path insert above

REPO = os.environ.get("GH_REPO", "")
PR = os.environ.get("PR_NUMBER", "")
ACTOR = os.environ.get("ACTOR", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ENDPOINT = os.environ.get("ENDPOINT_NAME", "modelops-reviewer")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-glm-5-2")
# Short run id — passed in via modelops-fix.yml env (GITHUB_RUN_ID). Falls back to
# "local" so local test runs don't break.
RUN_ID = os.environ.get("RUN_ID", "local")
_GH = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}


def gh_get(path: str) -> dict:
    r = requests.get(f"https://api.github.com{path}", headers=_GH, timeout=30)
    r.raise_for_status()
    return r.json()


def gh_post(path: str, body: dict) -> dict:
    r = requests.post(f"https://api.github.com{path}", headers=_GH, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def comment(body: str) -> None:
    requests.post(
        f"https://api.github.com/repos/{REPO}/issues/{PR}/comments",
        headers=_GH,
        json={"body": body},
        timeout=30,
    )


def get_findings(diff: str) -> list[dict]:
    from databricks.sdk import WorkspaceClient  # lazy: import errors stay inside main's guard

    w = WorkspaceClient()
    resp = w.api_client.do(
        "POST",
        f"/serving-endpoints/{ENDPOINT}/invocations",
        body={"input": [{"role": "user", "content": diff or "(empty diff)"}]},
    )
    text = "".join(
        c.get("text", "")
        for it in (resp.get("output") or [])
        for c in (it.get("content") or [])
        if isinstance(c, dict)
    )
    return review_core.parse_review(text)["findings"]


def retrieve_rules(query_text: str) -> list[dict]:
    """Handbook rules for the fix prompt — queries the Knowledge Assistant (KA) endpoint
    so the bot's fix follows the ACTUAL handbook, not just finding summaries.
    Best-effort: a fix still proceeds (on the finding citations) if retrieval fails."""
    # KA serving endpoint is auto-named by Agent Bricks (not the display name); overridable.
    ka_endpoint = os.environ.get("KA_ENDPOINT", "ka-5f315d3c-endpoint")
    try:
        from databricks.sdk import WorkspaceClient  # lazy

        w = WorkspaceClient()
        # KA endpoint uses the Responses API: `input`, NOT `messages`.
        resp = w.api_client.do(
            "POST",
            f"/serving-endpoints/{ka_endpoint}/invocations",
            body={
                "input": [
                    {
                        "role": "user",
                        "content": (
                            "Which ModelOps Handbook rules are relevant for fixing this code? "
                            f"{query_text[:1500]}"
                        ),
                    }
                ]
            },
        )
        # KA returns cited answer text — wrap as a single synthetic rule so
        # build_fix_prompt can include it as grounding context. The KA speaks the
        # Responses API (output[].content[].text); tolerate chat-completions too.
        ka_text = ""
        for item in (resp.get("output") or []):
            for c in (item.get("content") or []):
                if isinstance(c, dict) and c.get("text"):
                    ka_text += c["text"]
                elif isinstance(c, str):
                    ka_text += c
        if not ka_text:
            for choice in (resp.get("choices") or []):
                ka_text += (choice.get("message") or {}).get("content", "")
        if ka_text.strip():
            return [
                {
                    "rule_id": "KA-GROUNDING",
                    "citation": f"modelops-handbook-ka ({ka_endpoint})",
                    "content": ka_text.strip()[:2000],
                    "title": "Knowledge Assistant grounding",
                    "severity_hint": "SUGGESTION",
                }
            ]
    except Exception as e:  # noqa: BLE001 — retrieval is best-effort
        print(f"KA rule retrieval degraded: {type(e).__name__}: {e}")
    return []


def _fm_call(system: str, user: str) -> str | None:
    # Call GLM-5-2 via the SDK's OpenAI-compatible client. On the CI runner the SP
    # authenticates with oauth-m2m (no static PAT), so cfg.token is None and constructing
    # openai.OpenAI(api_key=...) directly fails with "Missing credentials". get_open_ai_client()
    # wraps the SDK's dynamic OAuth token minting, so it works under oauth-m2m.
    from databricks.sdk import WorkspaceClient  # lazy

    client = WorkspaceClient().serving_endpoints.get_open_ai_client()
    resp = client.chat.completions.create(
        model=LLM_ENDPOINT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=4000,
        temperature=0.0,
    )
    return review_core.extract_code(resp.choices[0].message.content)


def fm_fix(path: str, original: str, findings: list[dict], rules: list[dict]) -> str | None:
    system, user = review_core.build_fix_prompt(path, original, findings, rules)
    return _fm_call(system, user)


def _run_linter(path: str) -> tuple[bool, str]:
    """Verify the generated fix against the deterministic gate ON THE FILE (repo config).
    For Python, first APPLY `ruff format` (deterministic) so the fix is format-clean —
    pr-checks runs BOTH `ruff check` AND `ruff format --check`, so a lint-clean-but-
    unformatted fix would still fail CI. Returns (passed, combined_output)."""
    linter = review_core.linter_for(path)
    if linter == "ruff":
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(["ruff", "format", path], capture_output=True, text=True)  # noqa: S603,S607
        cmd = ["ruff", "check", path]
    elif linter == "sqlfluff":
        cmd = ["sqlfluff", "lint", path]
    else:
        return True, ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603,S607
    except FileNotFoundError:
        print(f"{linter} not installed in the fix job — skipping lint gate for {path}")
        return True, ""
    return r.returncode == 0, (r.stdout + r.stderr)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)  # noqa: S603,S607


def main() -> None:
    if not (REPO and PR and GH_TOKEN and BOT_TOKEN):
        print("missing GH_REPO/PR_NUMBER/GH_TOKEN/BOT_TOKEN — skipping (non-blocking)")
        return

    pr = gh_get(f"/repos/{REPO}/pulls/{PR}")
    head_ref = pr["head"]["ref"]
    head_repo = (pr.get("head", {}).get("repo") or {}).get("full_name")
    base_repo = (pr.get("base", {}).get("repo") or {}).get("full_name")
    if head_repo != base_repo:
        comment("🤖 **ModelOps Bot**: autofix does not operate on fork PRs (security).")
        return

    try:
        perm = gh_get(f"/repos/{REPO}/collaborators/{ACTOR}/permission").get("permission", "none")
    except requests.HTTPError:
        perm = "none"
    try:
        protected = bool(gh_get(f"/repos/{REPO}/branches/{head_ref}").get("protected", False))
    except requests.HTTPError:
        protected = False
    ok, reason = review_core.is_authorized(perm, protected)
    if not ok:
        comment(f"🤖 **ModelOps Bot** cannot apply fix: {reason}")
        return

    diff = _git("--no-pager", "diff", f"origin/{pr['base']['ref']}...HEAD").stdout
    changed_files = {f["path"] for f in review_core.build_review_context(diff)["files"]}
    findings = get_findings(diff)
    by_file = review_core.select_fixable(findings, changed_files)  # confine to PR's changed files
    if not by_file:
        comment("🤖 **ModelOps Bot**: no applicable findings in this PR's changed files.")
        return

    changed: dict[str, str] = {}
    for path, fs in by_file.items():
        p = pathlib.Path(path)
        if not p.exists():
            continue
        original = p.read_text(encoding="utf-8")
        rules = retrieve_rules(original)  # handbook grounding for the fix
        new = fm_fix(path, original, fs, rules)
        valid, err = review_core.validate_content(path, new)
        if not valid:
            comment(
                f"🤖 **ModelOps Bot**: the proposed fix for `{path}` is not valid "
                f"({err}); no push was made."
            )
            return
        if not new or new == original:
            continue

        # Lint gate (+ ONE retry): the fix must ALSO pass Ruff/sqlfluff before we push, so
        # /modelops-fix never trades a handbook violation for a linter failure. We write the
        # candidate so the linter reads it with the repo's config, lint it, and if it fails
        # feed the exact errors back to the model for one more attempt.
        p.write_text(new, encoding="utf-8")
        lint_ok, lint_out = _run_linter(path)
        if not lint_ok:
            system, user = review_core.build_fix_retry_prompt(path, new, lint_out)
            retry = _fm_call(system, user)
            rvalid, _ = review_core.validate_content(path, retry)
            if rvalid and retry:
                p.write_text(retry, encoding="utf-8")
                lint_ok, lint_out = _run_linter(path)
                if lint_ok:
                    new = retry
            if not lint_ok:
                p.write_text(original, encoding="utf-8")  # revert working tree; push nothing
                comment(
                    f"🤖 **ModelOps Bot**: the fix for `{path}` kept failing the linter "
                    f"after a retry; no push was made.\n\n```\n{lint_out.strip()[:1000]}\n```"
                )
                return
        changed[path] = new

    if not changed:
        comment("🤖 **ModelOps Bot**: no applicable changes were generated.")
        return

    # Create a new fix branch, commit, push, open a PR, comment on the original PR.
    short_run = str(RUN_ID)[:8]
    fix_branch = f"modelops-fix/pr-{PR}-{short_run}"

    _git("config", "user.name", "ModelOps Bot")
    _git("config", "user.email", "modelops-bot@users.noreply.github.com")
    # Create and switch to the fix branch from current HEAD (which is the PR head).
    _git("checkout", "-b", fix_branch)
    _git("add", *changed)
    files = ", ".join(sorted(changed))
    _git("commit", "-m", f"fix(modelops): apply ModelOps Reviewer fixes ({files})")

    push = _git(
        "push",
        f"https://x-access-token:{BOT_TOKEN}@github.com/{REPO}.git",
        f"HEAD:{fix_branch}",
    )
    if push.returncode != 0:
        print(f"push failed: {push.stderr}")  # details to secret-masked Actions log only
        comment("🤖 **ModelOps Bot**: push failed (see workflow logs).")
        return

    # Open a new PR: base = original PR's head branch, head = fix branch.
    pr_body = (
        f"Automated fixes proposed by ModelOps Reviewer for PR #{PR}.\n\n"
        f"**Files changed:** {files}\n\n"
        f"Triggered via `/modelops-fix` on #{PR}."
    )
    try:
        new_pr = gh_post(
            f"/repos/{REPO}/pulls",
            {
                "title": f"fix(modelops): automated fixes for PR #{PR}",
                "head": fix_branch,
                "base": head_ref,
                "body": pr_body,
            },
        )
        fix_pr_url = new_pr.get("html_url", "(url unavailable)")
        fix_pr_number = new_pr.get("number", "")
        comment(
            f"🤖 **ModelOps Bot** opened fix PR #{fix_pr_number} with proposed fixes: "
            f"{fix_pr_url}\n\nFiles: `{files}`.\n\n"
            "Review and merge the fix PR into this branch to re-trigger review and CI."
        )
    except Exception as e:  # noqa: BLE001 — PR creation is best-effort
        # The branch + commit are already pushed — at least tell the user.
        comment(
            f"🤖 **ModelOps Bot** pushed fixes to branch `{fix_branch}` but could not open "
            f"a PR automatically ({type(e).__name__}: {str(e)[:200]}). "
            "You can open the PR manually."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — fix mode must never fail the job
        print(f"fix degraded: {type(e).__name__}: {e}")
        with contextlib.suppress(Exception):
            comment(
                "🤖 **ModelOps Bot**: could not complete autofix (see logs); "
                "the PR is not blocked."
            )
    sys.exit(0)

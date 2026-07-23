#!/usr/bin/env bash
# reset_demo.sh — Idempotent demo reset for ModelOps CI/CD demo.
#
# Usage:
#   bash scripts/reset_demo.sh              # reset state only (no PRs opened)
#   bash scripts/reset_demo.sh --open-prs   # reset + recreate demo PRs
#
# What it does:
#   1. Close any open PRs labeled "demo"; delete remote branches demo/* and modelops-fix/*
#   2. (--open-prs) Recreate scenario branches from main + apply bad-pr patches; open PRs
#   3. UC model reset: keep demand_forecaster v1, @champion → v1, remove @challenger
#   4. Clean up leftover mlops_guardian-* serving endpoints (defensive)
#   5. Print final state: PRs, model versions + aliases, endpoint states
#
# Requirements:
#   - gh CLI (authed as malcolndandaro)
#   - databricks CLI (profile agentic-mlops-cicd-aws)
#   - python 3.x with databricks-sdk installed (for MlflowClient)
#
# Safe to run twice — idempotent by design.

set -euo pipefail

PROFILE="agentic-mlops-cicd-aws"
REPO="malcolndandaro/modelops-cicd-demo"
CATALOG="malcoln_aws_stable_catalog"
SCHEMA="agentic2_mlops_dev"
MODEL="demand_forecaster"
CI_SP_CLIENT_ID="a66e1537-4dc5-4115-a50c-1e5d4143c688"  # sp-modelops-ci
MLFLOW_EXPERIMENT="/ModelOps/demand_forecaster_training"
OPEN_PRS="${1:-}"

# Color helpers
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
info(){ echo -e "${YELLOW}[..] $*${NC}"; }

echo ""
echo "=========================================="
echo "  ModelOps CI/CD Demo Reset"
echo "=========================================="
echo ""

# ---------------------------------------------------------------------------
# 1. Close open demo PRs and delete remote demo/* / modelops-fix/* branches
# ---------------------------------------------------------------------------
info "Step 1/5: Closing open demo PRs and removing demo/fix branches..."

# Close PRs labeled "demo" (open ones)
OPEN_DEMO_PRS=$(gh pr list --repo "$REPO" --label demo --state open --json number --jq '.[].number' 2>/dev/null || true)
if [ -n "$OPEN_DEMO_PRS" ]; then
    for pr in $OPEN_DEMO_PRS; do
        gh pr close "$pr" --repo "$REPO" --comment "Closed by reset_demo.sh" 2>/dev/null || true
        ok "  Closed PR #$pr"
    done
else
    ok "  No open demo PRs to close"
fi

# Delete remote demo/* and modelops-fix/* branches.
# gh api on an EMPTY repo returns a 409 error object (not an array), so filter through
# jq guarded by `if type=="array"` — otherwise the error JSON gets word-split into the loop.
delete_branches_by_prefix() {
    local prefix="$1"
    local refs
    refs=$(gh api "repos/${REPO}/git/refs" 2>/dev/null \
        | jq -r "if type==\"array\" then .[].ref else empty end | select(startswith(\"refs/heads/${prefix}\"))" 2>/dev/null || true)
    if [ -n "$refs" ]; then
        while IFS= read -r ref; do
            [ -z "$ref" ] && continue
            local branch="${ref#refs/heads/}"
            gh api --method DELETE "repos/${REPO}/git/refs/heads/${branch}" >/dev/null 2>&1 || true
            ok "  Deleted remote branch: $branch"
        done <<< "$refs"
    else
        ok "  No remote ${prefix}* branches to delete"
    fi
}
delete_branches_by_prefix "demo/"
delete_branches_by_prefix "modelops-fix/"

# ---------------------------------------------------------------------------
# 2. (--open-prs) Recreate scenario branches and open PRs
# ---------------------------------------------------------------------------
if [ "$OPEN_PRS" = "--open-prs" ]; then
    info "Step 2/5: Creating demo branches and opening PRs..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"

    # Ensure the 'demo' label exists — gh pr create --label fails hard if it's missing,
    # which would silently drop the PRs. Idempotent (no-op if it already exists).
    gh label create demo -R "$REPO" --color FF6B00 --description "Demo PRs (reset-managed)" 2>/dev/null || true

    # Scenario 1: ml-review-blocker
    BRANCH_1="demo/ml-review-blocker"
    info "  Creating branch $BRANCH_1..."

    # Get SHA of main
    MAIN_SHA=$(gh api "repos/${REPO}/git/ref/heads/main" --jq '.object.sha')

    # Create branch from main
    gh api --method POST "repos/${REPO}/git/refs" \
        --field "ref=refs/heads/${BRANCH_1}" \
        --field "sha=${MAIN_SHA}" 2>/dev/null || \
    gh api --method PATCH "repos/${REPO}/git/refs/heads/${BRANCH_1}" \
        --field "sha=${MAIN_SHA}" --field "force=true" 2>/dev/null || true

    # Scenario 1 is a PURE code-policy (ENV-01) violation: only pricing_adjustments.py
    # changes. We deliberately do NOT touch config.yml here — no model change means Gate 2
    # (the promotion gate) has nothing to flag, so the reviewer (Gate 1) is the SOLE blocker,
    # catching the semantic ENV-01 cross-env reference that the deterministic linters can't.
    PRICING_CONTENT=$(base64 < "${REPO_ROOT}/bad-pr/ml-review-blocker/pricing_adjustments.py")
    PRICING_SHA=$(gh api "repos/${REPO}/contents/src/jobs/pricing_adjustments.py?ref=${BRANCH_1}" --jq '.sha' 2>/dev/null || echo "")

    if [ -n "$PRICING_SHA" ]; then
        gh api --method PUT "repos/${REPO}/contents/src/jobs/pricing_adjustments.py" \
            --field "message=feat: add regional pricing reference to the adjustments job" \
            --field "content=${PRICING_CONTENT}" \
            --field "sha=${PRICING_SHA}" \
            --field "branch=${BRANCH_1}" > /dev/null
        ok "  Updated src/jobs/pricing_adjustments.py on $BRANCH_1 (ENV-01 violation)"
    fi

    # Open PR
    PR1_URL=$(gh pr create \
        --repo "$REPO" \
        --base main \
        --head "$BRANCH_1" \
        --title "feat: add regional pricing reference to the adjustments job" \
        --body "$(cat <<'PREOF'
## Summary

Adds a corporate pricing reference lookup to the price-adjustments job so regional
adjustments can use the gold pricing table.

**Expected demo outcome:** Ruff / sqlfluff / bundle-validate and the AI Promotion Gate all
pass — the change is syntactically clean and touches no model config. Only the **ModelOps
Reviewer** (Gate 1) blocks it, citing **ENV-01**: a dev-context job reads the prod schema
`agentic2_mlops_prod`. `/modelops-fix` rewrites it to `${var.catalog}.${var.schema}`.
PREOF
)" \
        --label demo 2>&1) || PR1_URL="$(gh pr list --repo "$REPO" --head "$BRANCH_1" --state open --json url --jq '.[0].url' 2>/dev/null)"
    if [ -z "$PR1_URL" ]; then
        echo "  WARNING: could not open PR for $BRANCH_1 — check 'gh pr create' output above"
    else
        ok "  PR ready: $PR1_URL"
    fi

    # Scenario 2: ml-gate-blocker
    BRANCH_2="demo/ml-gate-blocker"
    info "  Creating branch $BRANCH_2..."

    gh api --method POST "repos/${REPO}/git/refs" \
        --field "ref=refs/heads/${BRANCH_2}" \
        --field "sha=${MAIN_SHA}" 2>/dev/null || \
    gh api --method PATCH "repos/${REPO}/git/refs/heads/${BRANCH_2}" \
        --field "sha=${MAIN_SHA}" --field "force=true" 2>/dev/null || true

    CONFIG_CONTENT2=$(base64 < "${REPO_ROOT}/bad-pr/ml-gate-blocker/config.yml")
    CONFIG_SHA2=$(gh api "repos/${REPO}/contents/src/ml/config.yml?ref=${BRANCH_2}" --jq '.sha' 2>/dev/null || echo "")

    if [ -n "$CONFIG_SHA2" ]; then
        gh api --method PUT "repos/${REPO}/contents/src/ml/config.yml" \
            --field "message=demo: simplify demand_forecaster — reduce estimators and feature set" \
            --field "content=${CONFIG_CONTENT2}" \
            --field "sha=${CONFIG_SHA2}" \
            --field "branch=${BRANCH_2}" > /dev/null
        ok "  Updated src/ml/config.yml on $BRANCH_2"
    fi

    PR2_URL=$(gh pr create \
        --repo "$REPO" \
        --base main \
        --head "$BRANCH_2" \
        --title "perf: simplify demand_forecaster — reduce estimators and feature set" \
        --body "$(cat <<'PREOF'
## Summary

Reduces model complexity by cutting `n_estimators` from 100 to 5 and focusing on the
most predictive features. Updates `max_acceptable_mae` accordingly.

**Expected demo outcome:** Gate 1 passes (no policy violation). Gate 2 blocks — ML-03
(challenger MAE significantly worse than champion after dropping features and capacity).
PREOF
)" \
        --label demo 2>&1) || PR2_URL="$(gh pr list --repo "$REPO" --head "$BRANCH_2" --state open --json url --jq '.[0].url' 2>/dev/null)"
    if [ -z "$PR2_URL" ]; then
        echo "  WARNING: could not open PR for $BRANCH_2 — check 'gh pr create' output above"
    else
        ok "  PR ready: $PR2_URL"
    fi
else
    ok "Step 2/5: Skipped (run with --open-prs to also create demo PRs)"
fi

# ---------------------------------------------------------------------------
# 2.5 Ensure the CI SP can read/write the MLflow experiment folder.
# The training job runs AS the CI SP; if the experiment (or its /ModelOps parent) was
# first created by a human, the SP lacks read permission and `train` fails with
# "does not have read permission for node /workspace/<id>". Grant CAN_MANAGE (idempotent).
# ---------------------------------------------------------------------------
info "Step 2.5: Ensuring CI SP can access the MLflow experiment folder..."
_exp_status=$(databricks --profile "$PROFILE" workspace get-status "$MLFLOW_EXPERIMENT" -o json 2>/dev/null || echo "")
if [ -n "$_exp_status" ]; then
    _dir_id=$(databricks --profile "$PROFILE" workspace get-status "$(dirname "$MLFLOW_EXPERIMENT")" -o json 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('object_id',''))" 2>/dev/null || echo "")
    _exp_id=$(echo "$_exp_status" | python3 -c "import sys,json;print(json.load(sys.stdin).get('object_id',''))" 2>/dev/null || echo "")
    for pair in "directories:${_dir_id}" "experiments:${_exp_id}"; do
        _type="${pair%%:*}"; _oid="${pair##*:}"
        [ -z "$_oid" ] && continue
        databricks --profile "$PROFILE" api patch "/api/2.0/permissions/${_type}/${_oid}" \
            --json "{\"access_control_list\":[{\"service_principal_name\":\"$CI_SP_CLIENT_ID\",\"permission_level\":\"CAN_MANAGE\"}]}" >/dev/null 2>&1 \
            && ok "  Granted CI SP CAN_MANAGE on ${_type}/${_oid}" || true
    done
else
    ok "  Experiment not created yet — first training run (as the SP) will create + own it"
fi

# ---------------------------------------------------------------------------
# 2.6 Ensure the retail seed tables exist (fact_sales / dim_store).
# The pre-merge integration tests (tests/test_pipeline_serverless.py) read these real
# UC tables; if they're missing the gate fails with TABLE_OR_VIEW_NOT_FOUND. Seed once
# (idempotent — seed_retail.py overwrites). Skips if already present.
# ---------------------------------------------------------------------------
info "Step 2.6: Ensuring retail seed tables (fact_sales/dim_store) exist..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
if databricks --profile "$PROFILE" tables get "${CATALOG}.${SCHEMA}.fact_sales" >/dev/null 2>&1; then
    ok "  Seed tables already present"
else
    info "  Seeding retail source tables (Databricks Connect serverless)..."
    if DATABRICKS_CONFIG_PROFILE="$PROFILE" MODELOPS_SEED_SCHEMA="$SCHEMA" \
        python3 "${REPO_ROOT}/data/seed_retail.py" >/dev/null 2>&1; then
        ok "  Seeded ${CATALOG}.${SCHEMA}.fact_sales + dim_store"
    else
        echo "  WARNING: seed_retail.py failed — retail integration tests may fail. Run it manually."
    fi
fi

# ---------------------------------------------------------------------------
# 2.7 Ensure the CI SP OWNS the demand_forecaster model in every schema.
# register/promote run AS the CI SP; in UC only the model OWNER (or MANAGE holder) can
# create versions or move @champion/@challenger. A human-created (or human-owned) model
# fails these tasks with "PERMISSION_DENIED: ... does not have MANAGE on Routine or Model".
# Idempotently transfer ownership to the SP for all three schemas (best-effort; skips a
# schema whose model doesn't exist yet — the first SP deploy bootstraps + owns it).
# ---------------------------------------------------------------------------
info "Step 2.7: Ensuring CI SP owns the demand_forecaster model in all schemas..."
for _schema in agentic2_mlops_dev agentic2_mlops_staging agentic2_mlops_prod; do
    _fqn="${CATALOG}.${_schema}.${MODEL}"
    _owner=$(databricks --profile "$PROFILE" api get "/api/2.1/unity-catalog/models/${_fqn}" 2>/dev/null \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('owner',''))" 2>/dev/null || echo "")
    if [ -z "$_owner" ]; then
        ok "  ${_schema}: model not created yet — first SP deploy will bootstrap + own it"
    elif [ "$_owner" = "$CI_SP_CLIENT_ID" ]; then
        ok "  ${_schema}: already owned by CI SP"
    else
        databricks --profile "$PROFILE" api patch "/api/2.1/unity-catalog/models/${_fqn}" \
            --json "{\"owner\":\"$CI_SP_CLIENT_ID\"}" >/dev/null 2>&1 \
            && ok "  ${_schema}: ownership transferred to CI SP (was ${_owner})" \
            || echo "  WARNING: could not transfer ${_fqn} ownership (was ${_owner}) — register may fail as the SP"
    fi
done

# ---------------------------------------------------------------------------
# 3. UC model reset across ALL envs. Each environment now trains its OWN model
#    (dev pre-merge; qa/prod post-merge), so the reset must clean all three schemas:
#      - dev     → keep v1, @champion → v1, drop @challenger   (baseline for scenario 2's
#                  gate to compare against; the live runs re-train on top)
#      - staging → wipe all versions   (the post-merge deploy bootstraps qa fresh)
#      - prod    → wipe all versions   (the post-merge deploy bootstraps prod fresh)
# ---------------------------------------------------------------------------
info "Step 3/5: Resetting UC model across dev/staging/prod..."

python3 - <<PYEOF
import sys, os
try:
    import mlflow
    from mlflow.tracking import MlflowClient
except ImportError as e:
    print(f"  [SKIP] Missing dependency: {e}. Install databricks-sdk and mlflow.")
    sys.exit(0)

os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "${PROFILE}")
catalog, model_name = "${CATALOG}", "${MODEL}"
mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()

def reset_env(schema, keep_v1):
    fqn = f"{catalog}.{schema}.{model_name}"
    try:
        versions = client.search_model_versions(f"name='{fqn}'")
    except Exception:
        print(f"  [OK] {schema}: model does not exist yet (bootstraps on first run)")
        return
    if not versions:
        print(f"  [OK] {schema}: no versions (clean)")
        return
    if keep_v1:
        # keep v1 (or lowest) as @champion, drop @challenger, delete the rest
        lowest = sorted(versions, key=lambda v: int(v.version))[0].version
        for a in ("challenger",):
            try: client.delete_registered_model_alias(fqn, a)
            except Exception: pass
        client.set_registered_model_alias(fqn, "champion", lowest)
        for v in versions:
            if v.version != lowest:
                try: client.delete_model_version(fqn, v.version)
                except Exception: pass
        print(f"  [OK] {schema}: @champion=v{lowest}, @challenger removed, extra versions deleted")
    else:
        # wipe: drop aliases then all versions, so the env bootstraps fresh next deploy
        for a in ("champion", "challenger"):
            try: client.delete_registered_model_alias(fqn, a)
            except Exception: pass
        for v in versions:
            try: client.delete_model_version(fqn, v.version)
            except Exception: pass
        print(f"  [OK] {schema}: wiped ({len(versions)} version(s)) — will bootstrap on deploy")

reset_env("agentic2_mlops_dev", keep_v1=True)
reset_env("agentic2_mlops_staging", keep_v1=False)
reset_env("agentic2_mlops_prod", keep_v1=False)
PYEOF

# ---------------------------------------------------------------------------
# 4. Clean up leftover mlops_guardian-* serving endpoints (defensive)
# ---------------------------------------------------------------------------
info "Step 4/5: Cleaning up leftover mlops_guardian-* serving endpoints..."

python3 - <<PYEOF
import os
import sys

os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "${PROFILE}")

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    print("  [SKIP] databricks-sdk not available")
    sys.exit(0)

try:
    w = WorkspaceClient(profile="${PROFILE}")
    endpoints = list(w.serving_endpoints.list())
    guardian_endpoints = [ep for ep in endpoints if ep.name and ep.name.startswith("mlops_guardian-")]
    if guardian_endpoints:
        for ep in guardian_endpoints:
            try:
                w.serving_endpoints.delete(name=ep.name)
                print(f"  [OK] Deleted leftover endpoint: {ep.name}")
            except Exception as e:
                print(f"  [WARN] Could not delete {ep.name}: {e}")
    else:
        print("  [OK] No mlops_guardian-* endpoints to clean up")
except Exception as e:
    print(f"  [WARN] Could not check serving endpoints: {e}")
PYEOF

# ---------------------------------------------------------------------------
# 5. Final state print
# ---------------------------------------------------------------------------
info "Step 5/5: Final state summary..."
echo ""
echo "--- Open demo PRs ---"
gh pr list --repo "$REPO" --label demo --state open --json number,title,headRefName \
    --jq '.[] | "  PR #\(.number): \(.headRefName) — \(.title)"' 2>/dev/null || echo "  (none)"

echo ""
echo "--- UC model demand_forecaster aliases ---"
python3 - <<PYEOF
import os, sys
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "${PROFILE}")
try:
    import mlflow
    mlflow.set_registry_uri("databricks-uc")
    from mlflow.tracking import MlflowClient
    client = MlflowClient()
    full_name = "${CATALOG}.${SCHEMA}.${MODEL}"
    try:
        versions = client.search_model_versions(f"name='{full_name}'")
        print(f"  Model: {full_name}  ({len(versions)} version(s))")
        # Query the two demo aliases authoritatively (v.aliases from search is unreliable
        # across mlflow versions — get_model_version_by_alias is the source of truth).
        for alias in ("champion", "challenger"):
            try:
                mv = client.get_model_version_by_alias(full_name, alias)
                print(f"  @{alias} -> v{mv.version}")
            except Exception:
                print(f"  @{alias} -> (none)")
    except Exception as e:
        print(f"  (model not found — will be created on first training run): {e}")
except ImportError:
    print("  (mlflow not installed — skipping model check)")
PYEOF

echo ""
echo "--- Key serving endpoints ---"
for EP in modelops-reviewer "${KA_ENDPOINT:-ka-5f315d3c-endpoint}"; do
    DATABRICKS_CONFIG_PROFILE="$PROFILE" databricks serving-endpoints get "$EP" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('state',{}); print(f'  {d.get(\"name\",\"$EP\")}: {s.get(\"ready\",\"?\")} ({s.get(\"config_update\",\"?\")})')" \
        || echo "  $EP: (not found or not accessible)"
done

echo ""
ok "Demo reset complete."
echo ""
echo "  Next steps:"
echo "   - Confirm the runner is online (GitHub → Settings → Actions → Runners)"
echo "   - Warm up endpoints with a test call if needed"
if [ "$OPEN_PRS" = "--open-prs" ]; then
echo "   - PRs are open and ready at: https://github.com/$REPO/pulls"
else
echo "   - Run with --open-prs to also create the demo PRs"
fi
echo ""

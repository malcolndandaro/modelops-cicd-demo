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

# Delete remote demo/* branches
DEMO_BRANCHES=$(gh api "repos/${REPO}/git/refs" --jq '.[].ref | select(startswith("refs/heads/demo/"))' 2>/dev/null || true)
if [ -n "$DEMO_BRANCHES" ]; then
    for ref in $DEMO_BRANCHES; do
        branch="${ref#refs/heads/}"
        gh api --method DELETE "repos/${REPO}/git/refs/heads/${branch}" 2>/dev/null || true
        ok "  Deleted remote branch: $branch"
    done
else
    ok "  No remote demo/* branches to delete"
fi

# Delete remote modelops-fix/* branches
FIX_BRANCHES=$(gh api "repos/${REPO}/git/refs" --jq '.[].ref | select(startswith("refs/heads/modelops-fix/"))' 2>/dev/null || true)
if [ -n "$FIX_BRANCHES" ]; then
    for ref in $FIX_BRANCHES; do
        branch="${ref#refs/heads/}"
        gh api --method DELETE "repos/${REPO}/git/refs/heads/${branch}" 2>/dev/null || true
        ok "  Deleted remote branch: $branch"
    done
else
    ok "  No remote modelops-fix/* branches to delete"
fi

# ---------------------------------------------------------------------------
# 2. (--open-prs) Recreate scenario branches and open PRs
# ---------------------------------------------------------------------------
if [ "$OPEN_PRS" = "--open-prs" ]; then
    info "Step 2/5: Creating demo branches and opening PRs..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"

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

    # Get current tree SHA and blob contents for the changed files
    # Push config.yml change via GitHub Contents API
    CONFIG_CONTENT=$(base64 < "${REPO_ROOT}/bad-pr/ml-review-blocker/config.yml")
    PRICING_CONTENT=$(base64 < "${REPO_ROOT}/bad-pr/ml-review-blocker/pricing_adjustments.py")

    # Get current file SHAs for update
    CONFIG_SHA=$(gh api "repos/${REPO}/contents/src/ml/config.yml?ref=${BRANCH_1}" --jq '.sha' 2>/dev/null || echo "")
    PRICING_SHA=$(gh api "repos/${REPO}/contents/src/jobs/pricing_adjustments.py?ref=${BRANCH_1}" --jq '.sha' 2>/dev/null || echo "")

    if [ -n "$CONFIG_SHA" ]; then
        gh api --method PUT "repos/${REPO}/contents/src/ml/config.yml" \
            --field "message=demo: increase n_estimators without updating regression test (ML-01 + ENV-01 scenario)" \
            --field "content=${CONFIG_CONTENT}" \
            --field "sha=${CONFIG_SHA}" \
            --field "branch=${BRANCH_1}" > /dev/null
        ok "  Updated src/ml/config.yml on $BRANCH_1"
    fi

    if [ -n "$PRICING_SHA" ]; then
        gh api --method PUT "repos/${REPO}/contents/src/jobs/pricing_adjustments.py" \
            --field "message=demo: add prod schema reference in dev job (ENV-01 violation)" \
            --field "content=${PRICING_CONTENT}" \
            --field "sha=${PRICING_SHA}" \
            --field "branch=${BRANCH_1}" > /dev/null
        ok "  Updated src/jobs/pricing_adjustments.py on $BRANCH_1"
    fi

    # Open PR
    PR1_URL=$(gh pr create \
        --repo "$REPO" \
        --base main \
        --head "$BRANCH_1" \
        --title "feat: tune demand_forecaster — increase n_estimators and add pricing reference" \
        --body "$(cat <<'PREOF'
## Summary

Increases `n_estimators` from 100 to 200 for better model accuracy. Also adds a pricing
reference lookup for the regional adjustment logic.

**Expected demo outcome:** Gate 1 blocks — ML-01 (hyperparameter change without updating
regression test) and ENV-01 (cross-env reference to agentic2_mlops_prod schema).
PREOF
)" \
        --label demo 2>/dev/null || echo "already exists")
    ok "  Opened PR: $PR1_URL"

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
        --label demo 2>/dev/null || echo "already exists")
    ok "  Opened PR: $PR2_URL"
else
    ok "Step 2/5: Skipped (run with --open-prs to also create demo PRs)"
fi

# ---------------------------------------------------------------------------
# 3. UC model reset: keep demand_forecaster v1, @champion → v1, remove @challenger
# ---------------------------------------------------------------------------
info "Step 3/5: Resetting UC model aliases for demand_forecaster..."

python3 - <<PYEOF
import sys

try:
    from mlflow.tracking import MlflowClient
    from databricks.sdk import WorkspaceClient
    import mlflow
    import os
except ImportError as e:
    print(f"  [SKIP] Missing dependency: {e}. Install databricks-sdk and mlflow.")
    sys.exit(0)

catalog = "${CATALOG}"
schema = "${SCHEMA}"
model_name = "${MODEL}"
full_name = f"{catalog}.{schema}.{model_name}"

# Configure MLflow to use the Databricks workspace via the CLI profile
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "${PROFILE}")

try:
    mlflow.set_registry_uri("databricks-uc")
    client = MlflowClient()

    # Check if model exists
    try:
        versions = client.search_model_versions(f"name='{full_name}'")
    except Exception as e:
        print(f"  [SKIP] Model {full_name} does not exist yet (first run): {e}")
        sys.exit(0)

    if not versions:
        print(f"  [SKIP] No versions found for {full_name} (first run)")
        sys.exit(0)

    # Find v1
    v1 = None
    for v in versions:
        if v.version == "1":
            v1 = v
            break

    if v1 is None:
        # Use the lowest version as v1 equivalent
        sorted_versions = sorted(versions, key=lambda v: int(v.version))
        v1 = sorted_versions[0]
        print(f"  No explicit v1 found, using version {v1.version} as champion baseline.")

    champion_version = v1.version

    # Remove @challenger alias if it exists
    try:
        alias_info = client.get_model_version_by_alias(full_name, "challenger")
        client.delete_registered_model_alias(full_name, "challenger")
        print(f"  [OK] Removed @challenger alias (was on v{alias_info.version})")
    except Exception:
        print(f"  [OK] No @challenger alias to remove")

    # Set @champion → v1
    client.set_registered_model_alias(full_name, "champion", champion_version)
    print(f"  [OK] Set @champion -> v{champion_version}")
    print(f"  [OK] Model {full_name} reset: @champion=v{champion_version}, @challenger=removed")

except Exception as e:
    print(f"  [WARN] Could not reset UC model: {e}")
    print("  If the model does not exist yet, this is expected on the first run.")
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
        print(f"  Model: {full_name}")
        for v in sorted(versions, key=lambda x: int(x.version)):
            aliases = v.aliases if hasattr(v, 'aliases') else []
            print(f"  v{v.version} — aliases: {aliases if aliases else '(none)'}")
    except Exception as e:
        print(f"  (model not found — will be created on first training run): {e}")
except ImportError:
    print("  (mlflow not installed — skipping model check)")
PYEOF

echo ""
echo "--- Key serving endpoints ---"
DATABRICKS_CONFIG_PROFILE="$PROFILE" databricks serving-endpoints get modelops-reviewer 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  modelops-reviewer: {d.get(\"state\",{}).get(\"ready\",\"?\")} ({d.get(\"state\",{}).get(\"config_update\",\"?\")})')" \
    || echo "  modelops-reviewer: (not found or not accessible)"

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

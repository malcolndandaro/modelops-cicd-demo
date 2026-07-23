---
id: 0001
title: "ModelOps CI/CD demo — two AI gates for ML model promotion on Databricks"
labels: [ready-for-agent]
type: spec
created: 2026-07-22
---

# ModelOps CI/CD demo — two AI gates for ML model promotion on Databricks

## Problem Statement

Malcoln (Databricks SSA) has a customer meeting in a few hours and needs a live, reliable
demo of **end-to-end CI/CD for ML/AI assets on Databricks**. The customer's explicit ask:
Databricks Asset Bundles with Git-based promotion (dev → staging → prod), MLflow
registry/versioning/promotion, and — the headline — an **AI/LLM validation gate that
approves or blocks a model promotion** based on model quality, evaluation, and config/code
checks, plus best practices they can adopt.

A prior attempt (in a separate `../petrobras/` working copy) collapsed under its own
complexity and produced constant errors. The presenter needs a fresh, resettable,
repeatable demo that reuses what already works rather than rebuilding from zero. The demo
must survive a live audience: nothing that depends on a cold serving endpoint may hard-fail
the flow, and the whole thing must reset idempotently in under a minute between runs.

The demo must carry **generic, non-customer-specific branding** ("ModelOps"), be in English,
and run entirely in one workspace/catalog with environment separation by schema.

## Solution

Adapt the existing, ~80%-complete `bimbo_demo` end-to-end CI/CD repository (a Data
Engineering demo with an AI code reviewer) into a **classic-ML promotion narrative** with
**two AI gates**, rebranded generically as **ModelOps**:

- **Gate 1 — PR Reviewer (semantic/policy gate):** on every pull request, a custom AI
  reviewer reads the diff, retrieves the relevant standards from a **Knowledge Assistant**
  grounded on the ModelOps CI/CD + ML handbook, and posts cited, severity-tagged findings
  plus a GitHub Check Run. It catches policy problems deterministic linters cannot (e.g. a
  hyperparameter change with no matching update to the metric-regression test, or a config
  referencing another environment's catalog/schema).
- **Gate 2 — Promotion Gate (model-quality gate):** after merge, a training job trains a
  challenger model, registers it to Unity Catalog under an alias, then an LLM-driven gate
  compares the challenger's metrics against the current champion (plus the training-config
  diff) and decides `APPROVE` or `BLOCK`. Only on `APPROVE` is the `@champion` alias moved
  to the challenger. The decision is instrumented with MLflow tracing so the reasoning is
  visible in the MLflow UI during the demo.

The narrative shows two independent layers of defense: Gate 1 blocks a bad PR at review
time; Gate 2 blocks a "clean" PR that nonetheless degrades the model at promotion time.
Human approval gates (GitHub Environments) still guard each deploy — the AI is a first
filter, not the decision-maker.

The demo runs against a single workspace and catalog, with dev/staging/prod separated by
schema, and is fully resettable via a script.

## User Stories

### Presenter / demo operation

1. As the presenter, I want to run a single reset script before the meeting, so that the
   repo, GitHub PRs, and Unity Catalog model state return to a known clean baseline in
   under a minute.
2. As the presenter, I want the reset to be idempotent, so that running it twice in a row
   leaves the exact same state with no errors.
3. As the presenter, I want a pre-demo checklist and health-check, so that I can confirm
   every live dependency (serving endpoints warm, self-hosted runner online, Knowledge
   Assistant ready, GitHub environments configured) before I present.
4. As the presenter, I want a step-by-step runbook in the demo's language with expected
   timings and a plan B for each failure point, so that I can recover gracefully live.
5. As the presenter, I want a backup recording cue in the runbook, so that a live
   infrastructure hiccup never sinks the meeting.
6. As the presenter, I want all branding to be generic ("ModelOps", generic domain), so
   that nothing on screen ties the demo to a specific customer.

### Gate 1 — PR Reviewer

7. As a reviewer of ML PRs, I want the AI reviewer to read each PR diff and post findings
   as a PR comment, so that policy issues are surfaced inline.
8. As a reviewer, I want findings grounded in and cited to the ModelOps handbook via a
   Knowledge Assistant, so that each finding references an authoritative rule rather than a
   model's opinion.
9. As a reviewer, I want findings tagged by severity (BLOCKER / SUGGESTION / STYLE), so
   that only genuinely blocking issues gate the merge.
10. As a reviewer, I want a GitHub Check Run whose conclusion reflects the severity gate, so
    that the merge button is blocked only when a BLOCKER is present (once the check is
    required).
11. As a maintainer, I want to comment `/modelops-fix` to have the agent propose a fix, so
    that mechanical corrections don't cost me manual work.
12. As a maintainer, I want the fix delivered as a **new PR against my PR's branch** (not a
    silent direct push), so that I can review the bot's change before it lands.
13. As a platform owner, I want the reviewer to be a governed, versioned Unity Catalog asset
    deployed by the same pipeline it guards, so that the reviewer itself follows
    agent-as-code discipline.
14. As a maintainer, I want the reviewer to never hard-fail CI on infrastructure problems,
    so that a cold endpoint degrades to an advisory comment rather than blocking all PRs.

### Gate 2 — Promotion Gate

15. As an ML engineer, I want a training job that trains a demand-forecasting model quickly
    (<2 min), logs the run to MLflow, and registers it to Unity Catalog, so that every merge
    produces a candidate model.
16. As an ML engineer, I want the newly registered version to receive the `@challenger`
    alias, so that it is clearly distinguished from the live `@champion`.
17. As an ML engineer, I want a promotion gate task that compares the challenger's metrics
    to the current champion's and reads the training-config diff, so that promotion is
    evidence-based.
18. As an ML engineer, I want the promotion gate to call an LLM with the ML handbook rules
    injected and return a structured `APPROVE`/`BLOCK` decision with findings and a
    justification, so that the decision is explainable.
19. As an ML engineer, I want the gate to auto-approve on the very first run when no
    champion exists (bootstrap), so that the pipeline can establish an initial champion.
20. As an ML engineer, I want `@champion` moved to the challenger only when the gate
    approves, so that a degraded model never becomes champion automatically.
21. As an ML engineer, I want the gate's steps instrumented with MLflow tracing/spans, so
    that I can show the gate's reasoning and inputs in the MLflow UI.
22. As an ML engineer, I want a hardcoded metric-regression test in the test suite, so that
    a hyperparameter/feature change that worsens the model is caught — and so that
    "forgetting" to update it becomes a demonstrable policy violation.
23. As an ML engineer, I want the promotion gate wired into the deploy workflow at the
    appropriate stage, so that promotion happens as part of Git-based promotion, not
    manually.

### Environments, auth, governance

24. As a platform owner, I want dev/staging/prod separated by schema within one catalog, so
    that the whole demo runs safely in one place while still showing environment promotion.
25. As a platform owner, I want CI to authenticate to Databricks as a dedicated non-human
    service principal via OAuth M2M, so that the pipeline runs under a governed identity.
26. As a platform owner, I want human approval gates (GitHub Environments) on staging and
    prod promotions, so that a human still authorizes each environment promotion.
27. As a platform owner, I want model promotion to use Unity Catalog aliases
    (`@champion`/`@challenger`), not deprecated workspace-registry stages, so that the demo
    reflects current best practice and I can speak to "stage transitions" correctly.
28. As a security-conscious owner, I want a public repo with zero secrets and zero workspace
    identifiers committed, so that publishing to a personal GitHub account is safe.

### Demo scenarios (the two-gate payoff)

29. As the presenter, I want a "review-blocker" bad PR (changes a hyperparameter without
    updating the regression test, and references another environment's catalog/schema in a
    dev config), so that Gate 1 visibly blocks it citing the handbook.
30. As the presenter, I want a "gate-blocker" bad PR (a clean change that passes review but
    degrades the model, e.g. drops an important feature or slashes model capacity), so that
    Gate 1 passes but Gate 2 blocks it — demonstrating why the promotion gate exists.
31. As the presenter, I want to run `/modelops-fix` on the review-blocker PR and see the bot
    open a fix PR that makes the original PR green, so that the self-correcting loop is
    shown live.

## Implementation Decisions

### Foundation
- **Copy + rebrand, not from-scratch.** Start from a clean copy of the working `bimbo_demo`
  repository into the `petrobras2` working directory; rebrand all identifiers from
  Bimbo/Spanish to a generic English **ModelOps** identity. Reuse the CI plumbing
  (workflows, functional-core reviewer, DABs targets, tests) rather than rebuilding it.
- **Language:** English throughout (code, handbook, agent output, runbook) — drops the
  Spanish-narration burden of the source repo.
- **Domain:** generic **demand forecasting** (`demand_forecaster` model), replacing the
  bakery/pricing domain, with a synthetic data seed.

### Environment & auth
- **Single workspace / single catalog.** Workspace profile `agentic-mlops-cicd-aws`; catalog
  `malcoln_aws_stable_catalog`. Environments are separated by **schema**:
  `agentic2_mlops_dev` (dev), `agentic2_mlops_staging` (staging/"qa" in workflow terms),
  `agentic2_mlops_prod` (prod). DABs targets map one-to-one to these schemas.
- **CI identity:** a dedicated **OAuth M2M service principal**, granted `USE_CATALOG` on the
  catalog and `USE_SCHEMA`/`SELECT`/model+function privileges on the three schemas. The SP
  is not a workspace admin, so job `run_as` in production targets is set to the SP itself.
- **Self-hosted GitHub Actions runner is required.** The workspace is reachable only over
  VPN, so GitHub-hosted runners cannot reach it. Every Databricks-touching job runs on the
  self-hosted runner; pure-Python lint jobs may use hosted runners. Runner registration is a
  manual pre-demo step for the presenter.
- **Secret hygiene:** public repo. Secrets (SP OAuth secret, bot token) live in GitHub
  Actions secrets; non-secret config (host, SP client id) in repo variables. No secrets or
  workspace identifiers committed.

### LLM / model choices
- **LLM for all calls we control:** the Foundation Model endpoint `databricks-glm-5-2`
  (GLM-5-2). This powers both the custom reviewer agent's FM call and the promotion gate's
  direct call.
- **Knowledge Assistant (Agent Bricks):** a managed KA grounded on the ModelOps handbook
  docs (uploaded to a UC volume) provides Gate 1's retrieval + citations. It replaces
  bimbo's hand-built Vector Search index. The KA manages its own internal serving model; the
  GLM-5-2 choice applies to the calls the demo code makes directly.

### Gate 1 — PR Reviewer (Design 1: custom served agent + KA grounding)
- The reviewer remains a **custom MLflow `ResponsesAgent` on Databricks Model Serving**,
  registered to Unity Catalog and deployed by the pipeline (preserves the agent-as-code
  recursion). Its retrieval step queries the **Knowledge Assistant** for grounded, cited
  guidance instead of querying a raw Vector Search index directly.
- The pure decision logic stays in the existing functional core (finding parse, severity
  gate, check-run mapping, authz, fix-file selection). The CI shells invoke the endpoint and
  talk to GitHub.
- **Severity gate:** only BLOCKER findings drive the Check Run to `failure`; SUGGESTION/STYLE
  are advisory. CI always exits 0 — the Check Run conclusion is the gate, not the job exit
  code. A cold/unavailable endpoint yields an advisory "unavailable / non-blocking" comment.
- **Fix mode changes:** `/modelops-fix` opens a **new PR against the original PR's head
  branch** (checkout a new `modelops-fix/...` branch, apply the rewrite, commit under the
  bot identity, push, open PR, comment the link on the original PR) rather than pushing
  directly to the PR branch. Authz, bot identity, and error handling are preserved.

### Gate 2 — Promotion Gate (new)
- **Model training:** a simple, fast scikit-learn regression model (`demand_forecaster`)
  with simple features and a clear metric (MAE). Hyperparameters and model name live in a
  versioned training-config file so a PR can visibly change them.
- **Job structure:** a new serverless DABs job `model_training_job` with tasks:
  `train` (train + log MLflow run, MLflow ≥ 3) → `register` (register to UC as
  `<catalog>.<schema>.demand_forecaster`, new version gets `@challenger`) →
  `promotion_gate` → `promote` (move `@champion` to challenger, conditional on gate
  approval).
- **Promotion gate logic:** a new **pure core** builds the prompt from challenger-vs-champion
  metrics + config diff and parses the LLM's structured decision. Output contract (from the
  design): `{"decision": "APPROVE" | "BLOCK", "findings": [...], "justification": "..."}`,
  with defensive parsing (strip markdown fences). Bootstrap: if no `@champion` exists,
  auto-approve. The LLM call (GLM-5-2), MLflow tracing/spans, and the MlflowClient
  metric/alias reads/writes live in the imperative shell.
- **Gate outcome wiring:** `APPROVE` → the `promote` task runs; `BLOCK` → the job fails with
  the full parecer in the output/log (and, if cheap, a commit/PR comment via the existing
  GitHub client). Uses conditional task dependency or a raise to fail the job.
- **UC aliases only.** Promotion uses `@champion`/`@challenger` aliases; workspace-registry
  stages are explicitly not used (call this out in comments for the "stage transitions"
  question).
- **Deploy wiring:** the training job is plugged into the deploy workflow after dev deploy,
  within the staging/prod promotion flow, following the existing workflow pattern.

### Handbook / grounding content
- Add 4–5 ML-specific rules to the handbook (hyperparameter/feature change requires updating
  the metric-regression test in the same PR; models only in UC registry and `@champion` moved
  only by the pipeline; promotion requires challenger metric ≥ champion or a justified,
  approved degradation; training config must not reference another environment's
  catalog/schema). Feed the handbook to the Knowledge Assistant.

### Reset & demo scenarios
- **Two bad PRs:** `review-blocker` (hyperparameter change without regression-test update +
  cross-env reference → caught by Gate 1) and `gate-blocker` (clean change that degrades the
  model → passes Gate 1, blocked by Gate 2).
- **Reset script:** idempotent, < 1 min — closes demo PRs, deletes demo/fix branches,
  recreates the scenario branches/PRs, and resets Unity Catalog model state (keep v1, ensure
  `@champion` → v1, remove `@challenger`). Does not touch `main`. Also cleans up leftover
  serving endpoints from prior attempts (observed: `mlops_guardian-*`).

### Orchestration of the build
- Use the Agent Teams / subagents workflow to parallelize the slow provisioning (KA + custom
  agent endpoint deploys, SP creation) against the code build.

## Testing Decisions

- **What makes a good test here:** tests assert **external behavior** of the pure decision
  cores — given inputs (a diff / a set of metrics + config diff), the correct structured
  decision comes out — not implementation details, and with no network, MLflow, serving
  endpoint, or GitHub access. This is the existing functional-core / imperative-shell
  discipline of the source repo.
- **Seam 1 — `review_core.py` (existing, reused):** the pure core for Gate 1 (finding parse,
  severity gate, check-run mapping, authz, fix-file selection) keeps its existing unit-test
  suite (prior art: the repo's 37 core unit tests). Adapt tests where fix-mode behavior
  changed (new-PR-instead-of-direct-push) so they assert the new external behavior.
- **Seam 2 — `promotion_core.py` (new, highest seam for Gate 2):** unit tests over prompt
  construction from metrics + config diff, defensive JSON parsing of the decision
  (including markdown-fence stripping and malformed output), the bootstrap rule (no champion
  → APPROVE), and the metric-comparison logic. No LLM call, no MlflowClient, no tracing in
  the tested path — those are shell concerns.
- **Seam 3 — metric-regression test (model quality):** a hardcoded maximum-acceptable MAE
  test in the test suite. It exists both as a real guard and as a demo prop: bad-PR #1
  "forgets" to update it (a policy violation Gate 1 flags) and bad-PR #2 tries to pass it
  while degrading the model (Gate 2 catches what the threshold alone would miss).
- **Integration checks** (serverless, against the dev schema) follow the source repo's
  existing integration-test pattern; they are not the primary correctness seam.

## Out of Scope

- Rebuilding CI plumbing from scratch — the working plumbing is reused.
- Real catalog-per-environment isolation — the demo uses schema-per-environment in one
  catalog; true catalog-per-env is described as the future-state recommendation.
- Full AI Gateway governance suite (rate limits, PII guardrails, fallback) — inference-table
  logging only, as in the source repo; any cost figures are illustrative.
- The Azure DevOps publish layer — kept as a specified take-home, not implemented.
- Production hardening of the service principal, secrets rotation, and GitHub App identity —
  the demo uses a fine-grained token / M2M SP; production identities are described, not built.
- Any customer-specific ("Petrobras") branding or content.

## Further Notes

- **Primary live-risk (accepted):** Design 1 requires two serving endpoints (Knowledge
  Assistant + custom reviewer agent) provisioned and kept warm; first deploys are slow
  (~15 min each). Mitigations: start both deploys first and build the rest while they cook;
  keep the advisory-never-block CI pattern so a cold endpoint degrades gracefully;
  `scale_to_zero=false` plus a warm-up ping in the pre-demo checklist; a backup recording cue
  in the runbook.
- **Self-hosted runner** must be online at demo time — its registration and start are a
  manual pre-demo step for the presenter.
- **Verified environment facts:** endpoints `databricks-glm-5-2` and `databricks-gte-large-en`
  exist; catalog is owned by the presenter; the three `agentic2_mlops_*` schemas exist; no IP
  access lists are enabled (but VPN-only reachability still mandates the self-hosted runner).
- **Definition of done:** `databricks bundle validate` clean for all targets; the training
  job runs end-to-end in dev (train → register → gate approves on bootstrap → promote); the
  adapted fix-mode passes its unit tests; the reset script run twice consecutively ends in
  the same clean state; the runbook is complete.

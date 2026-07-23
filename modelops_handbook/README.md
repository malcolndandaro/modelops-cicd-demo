# ModelOps Handbook — Coding Standards

The single source of truth for ModelOps coding standards. These documents serve two consumers:

1. **The Knowledge Assistant** (`modelops-handbook-ka`) — an Agent Bricks Knowledge Assistant
   grounded on these docs, used both for team Q&A and as the retrieval layer for the reviewer.
2. **The ModelOps Reviewer** (automatic PR review) — on each diff the agent queries the
   Knowledge Assistant for the relevant standards and **cites the exact section** of the
   handbook in every finding.

## Rule format (parsed one row per rule)

Each rule is a block starting with `### [RULE-ID] Title`, followed by:

```
- **Severity:** BLOCKER | SUGGESTION | STYLE
- **Citation:** ModelOps Handbook › <Topic> › <RULE-ID>

<body: what the rule is, why, and a ❌/✅ example>
```

The `RULE-ID` prefix indicates the topic: `ENV` (Catalog-per-Env), `TP` (Transform Pattern),
`SQL` (SQL Conventions), `SEC` (PII & Secret Policy), `NM` (Naming), `DAB` (DABs Conventions),
and `ML` (ML Model Lifecycle — training, registry, and the promotion gate).

`Severity` is the suggested default; the Reviewer's severity gate decides the final effect
based on the diff's context.

## How it's grounded

The handbook docs are uploaded to the UC volume
`malcoln_aws_stable_catalog.agentic2_mlops_dev.handbook_volume` and indexed by the Knowledge
Assistant `modelops-handbook-ka`. To refresh after editing a rule, re-sync the KA's source
(re-upload the docs to the volume; the KA re-indexes them).

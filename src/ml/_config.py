"""Resolve catalog/schema config for the training tasks — argv → env → default.

Why argv first: the DABs job passes `--catalog/--schema` as spark_python_task parameters,
because job-level `parameters:` are NOT exposed as environment variables to a
spark_python_task (so relying on os.environ made every target silently train into the dev
default). CLI args resolve per-target (dev/qa/prd). Env vars are still honored as a fallback
for local/manual runs; the dev defaults are last.
"""

from __future__ import annotations

import os

_DEFAULT_CATALOG = "malcoln_aws_stable_catalog"
_DEFAULT_SCHEMA = "agentic2_mlops_dev"


def _arg(argv: list[str], flag: str) -> str | None:
    """Return the value following `--flag` in argv, or None."""
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def resolve_catalog_schema(argv: list[str] | None = None) -> tuple[str, str]:
    """Resolve (catalog, schema): --catalog/--schema argv → MLFLOW_* env → dev default."""
    import sys

    argv = argv if argv is not None else sys.argv
    catalog = _arg(argv, "--catalog") or os.environ.get("MLFLOW_CATALOG") or _DEFAULT_CATALOG
    schema = _arg(argv, "--schema") or os.environ.get("MLFLOW_SCHEMA") or _DEFAULT_SCHEMA
    return catalog, schema

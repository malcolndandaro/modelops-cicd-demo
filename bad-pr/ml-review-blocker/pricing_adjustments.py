# Databricks notebook source
"""Price adjustment calculation by store region.

Part of the retail pipeline — applies a price adjustment to sales using
the corporate pricing reference for the given region.

NOTE: This version contains a deliberate ENV-01 violation for the Gate 1 demo:
it reads the gold_pricing table from the PROD schema while running in a DEV context.

The file is deliberately LINT-CLEAN (Ruff/sqlfluff pass) — the only problem is the
semantic ENV-01 cross-env reference, which only the AI reviewer (Gate 1) can catch.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# ENV-01 BLOCKER: hardcoded prod schema reference in a dev-context job.
# A dev job must never read from the prod schema directly.
# Fix: use the DABs variable ${var.catalog}.${var.schema}.gold_pricing instead.
PROD_PRICING_REF = "malcoln_aws_stable_catalog.agentic2_mlops_prod.gold_pricing"


def apply_price_adjustments(region: str, pricing_reference: DataFrame, adjustments=None):
    """Return a transform that applies a price adjustment to sales rows.

    `region` is injected by currying; `pricing_reference` is passed as a DataFrame
    to keep the transform pure.
    """
    adjustments = adjustments or {}
    pct = adjustments.get("pct", 0.05)

    def _transform(df: DataFrame) -> DataFrame:
        region_baseline = (
            pricing_reference.filter(F.col("region") == region)
            .agg(F.first("base_price").alias("base_price"))
            .withColumn("adjusted_price", F.col("base_price") * (1 + pct))
            .select("adjusted_price")
        )

        return df.crossJoin(region_baseline)

    return _transform

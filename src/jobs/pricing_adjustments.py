# Databricks notebook source
"""Price adjustment calculation by store region.

Part of the retail pipeline — applies a price adjustment to sales using
the corporate pricing reference for the given region.

The gold_pricing table is referenced via DABs-injected variables so the same
code runs in all environments without editing.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# Catalog/schema are injected by DABs so the same code runs in dev, staging, and prod.
PRICING_REF = "${var.catalog}.${var.schema}.gold_pricing"


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

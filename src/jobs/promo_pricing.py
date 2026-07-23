"""Promotional pricing job for the retail pipeline (ModelOps demo)."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


def load_pricing_baseline(spark: SparkSession, catalog: str, schema: str) -> DataFrame:
    """Load the pricing baseline table for regional promotional adjustments."""
    table_name = f"{catalog}.{schema}.pricing_baseline"
    return spark.read.table(table_name)


def apply_promo(df: DataFrame, factor: float) -> DataFrame:
    """Apply a promotional factor to the base price."""
    return df.withColumn("promo_price", F.col("base_price") * F.lit(factor))

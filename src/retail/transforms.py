"""Pure DataFrame transforms for the retail sales pipeline.

Each function takes a DataFrame and returns a DataFrame — no side effects,
no reads/writes, no SparkSession in parameters. This makes them composable
via `df.transform(fn)` and testable with pytest. Vendored into this repo
so the job and integration tests can import it without sys.path hacks.

Reference: https://community.databricks.com/t5/technical-blog/how-to-use-the-transform-pattern-in-pyspark-for-modular-and/ba-p/117522
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def normalize_sku(df: DataFrame) -> DataFrame:
    """Normalize the SKU code: uppercase, strip spaces and special characters."""
    return df.withColumn(
        "sku",
        F.upper(F.regexp_replace(F.col("sku"), r"[^A-Za-z0-9]", "")),
    )


def filter_active_products(df: DataFrame) -> DataFrame:
    """Keep only active products."""
    return df.filter(F.col("is_active"))


def mark_returns(df: DataFrame) -> DataFrame:
    """Mark return rows (quantity < 0) and normalize the sign."""
    return df.withColumn("is_return", F.col("quantity") < 0).withColumn(
        "abs_quantity", F.abs(F.col("quantity"))
    )


def enrich_with_route(routes_df: DataFrame):
    """Currying: returns a transform that enriches sales rows with store/route info.

    Usage: `sales_df.transform(enrich_with_route(routes_df))`.
    """

    def _apply(sales_df: DataFrame) -> DataFrame:
        return sales_df.join(routes_df, on="store_id", how="left")

    return _apply


def calculate_route_revenue(df: DataFrame) -> DataFrame:
    """Aggregate revenue by route, separating sales from returns."""
    return df.groupBy("route_id", "route_name").agg(
        F.sum(F.when(~F.col("is_return"), F.col("amount")).otherwise(0)).alias("gross_revenue"),
        F.sum(F.when(F.col("is_return"), F.col("amount")).otherwise(0)).alias("returns_amount"),
        F.sum("amount").alias("net_revenue"),
        F.countDistinct("sku").alias("distinct_skus"),
    )


def build_daily_route_profitability(sales_df: DataFrame, routes_df: DataFrame) -> DataFrame:
    """Full pipeline in transform-pattern style: each step is independent and testable."""
    return (
        sales_df.transform(normalize_sku)
        .transform(filter_active_products)
        .transform(mark_returns)
        .transform(enrich_with_route(routes_df))
        .transform(calculate_route_revenue)
    )

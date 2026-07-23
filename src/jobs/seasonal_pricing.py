"""Seasonal pricing job for the retail pipeline (ModelOps demo)."""

from __future__ import annotations

from collections.abc import Callable

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window


def add_seasonal_price(season_factor: float) -> Callable[[DataFrame], DataFrame]:
    """Return a transform that applies a seasonal factor to the anchor price."""

    def _transform(sales: DataFrame) -> DataFrame:
        return sales.withColumn(
            "seasonal_price",
            F.col("base_price") * F.lit(season_factor),
        )

    return _transform


def attach_anchor_price(baseline: DataFrame) -> Callable[[DataFrame], DataFrame]:
    """Return a transform that declaratively attaches the anchor price from baseline."""

    season_window = Window.orderBy("season")
    anchor = (
        baseline.withColumn("rn", F.row_number().over(season_window))
        .where(F.col("rn") == 1)
        .select(F.col("base_price").alias("base_price"))
    )

    def _transform(sales: DataFrame) -> DataFrame:
        return sales.crossJoin(anchor)

    return _transform


def build_seasonal_prices(
    spark: SparkSession,
    catalog: str,
    schema: str,
    season_factor: float,
) -> DataFrame:
    """Build seasonal prices from the environment's baseline table."""
    baseline = spark.read.table(f"{catalog}.{schema}.seasonal_baseline")
    sales = spark.read.table(f"{catalog}.{schema}.fact_sales")

    return sales.transform(attach_anchor_price(baseline)).transform(
        add_seasonal_price(season_factor)
    )

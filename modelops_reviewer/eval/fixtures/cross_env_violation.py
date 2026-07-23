# Eval fixture (KNOWN-BAD): a dev job with a cross-env prod reference (ENV-01) and a
# driver-side .collect() inside transform logic (TP-02 / TP-01). Used by the eval
# harness to verify the reviewer catches the semantic findings. Not deployed.
# ruff: noqa: F821  (illustrative fixture; `spark` is a Databricks runtime global)
from pyspark.sql import functions as F


def adjust_prices(df, pct=0.05):
    baseline = df.select("base_price").collect()[0][0]  # driver action — TP-02
    # cross-env prod ref from a dev job — ENV-01
    prod = spark.table("malcoln_aws_stable_catalog.agentic2_mlops_prod.gold_pricing")
    return df.withColumn("adjusted", F.lit(baseline * (1 + pct))).join(prod, "sku")

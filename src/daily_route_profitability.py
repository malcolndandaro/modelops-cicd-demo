# Databricks notebook source
"""Job entrypoint — computes daily route profitability for the retail pipeline.

Orchestration layer: reads tables, calls the pure transforms vendored in
`retail/` (sibling of this file), writes results. Lives next to `retail/`
so Databricks has it on sys.path when running the notebook (no hacks needed).
"""

from retail.transforms import build_daily_route_profitability

# COMMAND ----------

dbutils.widgets.text("catalog", "malcoln_aws_stable_catalog")
dbutils.widgets.text("schema", "dev")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

# COMMAND ----------

sales = spark.read.table(f"{catalog}.{schema}.fact_sales")
routes = spark.read.table(f"{catalog}.{schema}.dim_store")

result = build_daily_route_profitability(sales, routes)

(result.write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.gold_route_profitability"))

print(f"Wrote {result.count()} rows to {catalog}.{schema}.gold_route_profitability")

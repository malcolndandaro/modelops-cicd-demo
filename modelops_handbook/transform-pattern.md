# Transform Pattern — Modular, testable logic

> Business logic is written as pure `df -> df` functions, composable with
> `DataFrame.transform()`. This is the ModelOps standard for testable PySpark code.

### [TP-01] Transformations are pure DataFrame -> DataFrame functions
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › Transform Pattern › TP-01

Each transformation step is a function that takes a DataFrame and returns a DataFrame — with
no table reads or writes, no SparkSession creation, and no side effects. That makes it
testable in seconds with a minimal DataFrame.
❌ A function that internally calls `spark.read`, `.write`, or takes `spark` as a parameter.
✅ `def filter_active_products(df: DataFrame) -> DataFrame: return df.filter(...)`.

### [TP-02] Avoid driver actions inside a transformation
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › Transform Pattern › TP-02

Do not use unnecessary `.collect()`, `.toPandas()`, `.first()`, or `.count()` inside the
transformation logic: they pull data to the driver, break parallelism, and usually hide a
design bug. Keep the work in Spark, declaratively.
❌ `baseline = df.select("base_price").collect()[0][0]` to then operate row by row.
✅ Compute with columns: `df.withColumn("adjusted", F.col("base_price") * (1 + pct))`.

### [TP-03] Name each transform by its intent and chain with .transform()
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › Transform Pattern › TP-03

The pipeline reads as a chain of clearly named transforms
(`df.transform(normalize_sku).transform(filter_active_products)`), not a monolithic block.
Each name describes what it does.

### [TP-04] Extra parameters via currying, not by reading sys.argv/env inside
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › Transform Pattern › TP-04

If a transform needs an extra parameter, use an outer function that returns the transform
(currying). Reading `sys.argv`, environment variables, or widgets inside the transformation
function makes it impure and untestable.
❌ `region = sys.argv[1]` inside the compute function.
✅ `def enrich_with_route(routes_df): def _t(df): ...; return _t`.

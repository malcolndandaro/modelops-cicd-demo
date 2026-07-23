# SQL Conventions — SQL style (dialect=databricks)

> ModelOps SQL conventions, aligned with the repo's sqlfluff configuration. The linter covers
> the style; these rules explain the why, and the agent cites them.

### [SQL-01] Keywords in UPPERCASE, identifiers in lowercase
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › SQL Conventions › SQL-01

Keywords (`SELECT`, `FROM`, `GROUP BY`) in uppercase; tables and columns in `lowercase`.
Mixing (`Route_Name`, `BASE_PRICE`) breaks consistency and diffs.

### [SQL-02] Explicit aliases with AS; do not order by ordinal
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › SQL Conventions › SQL-02

Every derived column gets an alias with `AS`. Do not use `ORDER BY 3` or `GROUP BY 1,2` by
position: name the columns so the query survives reordering.
❌ `sum(adjusted_price) total_adjusted … order by 3`.
✅ `SUM(adjusted_price) AS total_adjusted … ORDER BY total_adjusted DESC`.

### [SQL-03] Explicit columns in production views (no SELECT *)
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › SQL Conventions › SQL-03

Gold views and tables list columns explicitly. `SELECT *` couples the view to the upstream
schema and leaks new columns without control.

### [SQL-04] One identifier per line in long SELECTs
- **Severity:** STYLE
- **Citation:** ModelOps Handbook › SQL Conventions › SQL-04

In a SELECT with several columns, one per line with consistent indentation for clean diffs.

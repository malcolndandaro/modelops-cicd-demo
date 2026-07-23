# PII & Secret Policy — Sensitive data and credentials

> ModelOps security rules for handling secrets, SQL injection, and personal data (PII) in
> data code.

### [SEC-01] No secrets or credentials in code
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › PII & Secret Policy › SEC-01

Tokens, passwords, client secrets, connection strings, and API keys never go in source code or
notebooks. Use Databricks Secrets (`dbutils.secrets.get`) or a cloud key vault. A secret in a
public repo is considered compromised.
❌ `TOKEN = "dapi…"` or `password="…"` in code.
✅ `dbutils.secrets.get(scope="modelops", key="…")`.

### [SEC-02] Do not build SQL by interpolating external input
- **Severity:** BLOCKER
- **Citation:** ModelOps Handbook › PII & Secret Policy › SEC-02

Building queries by concatenating or interpolating external input (args, widgets, request)
opens SQL injection. Use parameterized queries / binds, or strict allowlist validation.
❌ `query = f"SELECT * FROM t WHERE region = '{region}'"` with `region` from `sys.argv`.
✅ Statement-execution parameters / binds, or validate `region` against an allowed set.

### [SEC-03] Do not log PII
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › PII & Secret Policy › SEC-03

Emails, names, addresses, phone numbers, and other personal data are not printed via `print`
or into logs. If traceability is needed, mask the value or use identifiers.

### [SEC-04] Access sensitive data via Unity Catalog governance
- **Severity:** SUGGESTION
- **Citation:** ModelOps Handbook › PII & Secret Policy › SEC-04

Access to sensitive columns goes through UC column masks / row filters, not by copying data
into ungoverned ad-hoc tables.

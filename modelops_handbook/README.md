# ModelOps Handbook — Coding Standards

Fuente única de verdad de los estándares de código de ModelOps. Estos documentos
sirven a dos consumidores:

1. **El Knowledge Assistant** (Q&A sobre el wiki) — Sesión 1.
2. **El ModelOps Reviewer** (revisión automática de PRs) — Sesión 2. El agente
   recupera las reglas relevantes a cada diff vía Vector Search y **cita la sección
   exacta** del handbook en cada hallazgo.

## Formato de regla (parseado a una fila por regla)

Cada regla es un bloque que empieza con `### [RULE-ID] Título`, seguido de:

```
- **Severity:** BLOCKER | SUGGESTION | STYLE
- **Citation:** ModelOps Handbook › <Tema> › <RULE-ID>

<cuerpo: qué es la regla, por qué, y un ejemplo ❌/✅>
```

El prefijo del `RULE-ID` indica el tema: `ENV` (Catalog-per-Env), `TP`
(Transform Pattern), `SQL` (SQL Conventions), `SEC` (PII & Secret Policy),
`NM` (Naming), `DAB` (DABs Conventions).

`Severity` es el *default* sugerido; el gate de severidad del Reviewer decide el
efecto final según el contexto del diff.

## Cómo se indexa

`modelops_reviewer/index/build_handbook_index.py` parsea estos `.md` a la tabla
`bimbo_demo.dev.modelops_handbook_rules` (una fila por regla, CDF habilitado) y crea
el índice Delta Sync `bimbo_demo.dev.modelops_handbook_rules_idx` sobre el endpoint
`modelops-vs` con embeddings `databricks-gte-large-en`.

Para reconstruir tras editar una regla:

```bash
DATABRICKS_AUTH_STORAGE=plaintext python modelops_reviewer/index/build_handbook_index.py
DATABRICKS_AUTH_STORAGE=plaintext python modelops_reviewer/index/verify_retrieval.py
```

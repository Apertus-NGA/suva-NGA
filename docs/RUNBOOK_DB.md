# RUNBOOK_DB: deploy, upgrade and reset the database

> Owner: the DDL owner (platform; the lead while D-024 is open). Sat 28 Nov 2026. Decisions: D-061 (fresh deploy, no `ALTER`), D-091 (schema guard, one-transaction deploy, READ COMMITTED). Cluster commands: `docs/DEPLOY.md`.

## 1. Deploy

- `make db-deploy` applies `src/db/sql/NN_*.sql` in order, **in one transaction**: a failure changes nothing (`tests/test_schema_guard.py::test_a_failed_deploy_leaves_nothing_behind`).
- It is idempotent. Tables, columns, constraints, indexes and ENUMs are created with `IF NOT EXISTS`; functions, views and triggers are replaced; seeds insert what is missing (`ON CONFLICT DO NOTHING`).
- It pins `default_transaction_isolation = 'read committed'` on the database. The source-row lock (D21) and the idempotent events (N1) wait for a lock, then read what the other transaction committed; under REPEATABLE READ they would not see it.
- In the cluster, `migrate` runs `make bootstrap`: the schema guard, the deploy, the login passwords.

## 2. When a reset is mandatory

The DDL never alters a table (D-061), so the database must be rebuilt when:

| Change | Detected by | Why a deploy is not enough |
|---|---|---|
| A table, column, constraint, index or ENUM value | the schema guard (`make db-schema-guard CMD=check`), before every cluster deploy | `IF NOT EXISTS` keeps the old object |
| A label of a seeded reason code | nothing: a human decision | the seed never overwrites a label (labels may be edited in place) |
| The meaning of `ops.source_snapshot.row_count` (PR #44) | `load_base`, which refuses an old snapshot | old rows count something else |
| A registry entry edited under the same version (`decision_ref`, `validation_ref`, config, rules) | `make db-registry`, which refuses | versions are immutable (D-064): bump the version instead when possible |

A change to a function, view or trigger only (for example D32) needs no reset: the guard says `same` and the deploy replaces it.

## 3. Reset

1. Back up: `make cluster-backup` (cluster) or `pg_dump --format=custom`.
2. Reset: `make db-reset` (host) or `docker compose run --rm migrate make db-reset` (cluster). It drops the six schemas and redeploys, and **refuses** if rows written by experts would be lost (export them first; `--discard-authored` only on a throwaway database).
3. Reload: `make db-registry`, `make ingest-base PARQUET=…`, `make ingest-gold`, `make layer1` (host), or `make cluster-up` (cluster: `load` and `pipeline` do it).
4. Check the closure: `make ingest-closure` exits 1 if a row of the source file is neither loaded nor excluded; `results/ingest_closure.json` has the counts per snapshot (aggregates only).

## 4. Changing the structure (the DDL owner)

1. Edit `src/db/sql/` (`CREATE … IF NOT EXISTS` in place, never `ALTER TABLE`).
2. On a throwaway database: `make db-reset && make db-deploy && make db-structure WRITE=1`, then `make db-test` and `pytest -m db`.
3. Commit `expected/db/structure.json` with the SQL: CI (`db` job) fails when the file does not match a fresh deploy.
4. Say in the PR that every existing database needs a reset (§2), and update `tests/sql/00_structure_test.sql` if the table or ENUM count changed.

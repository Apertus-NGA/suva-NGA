"""Schema fingerprint guard: deploy on an existing database only when it holds the same schema (docs/DEPLOY.md §7).

python -m src.db.schema_guard check     before `make db-deploy`: exit 1 when the database holds another schema
python -m src.db.schema_guard record    after it: store the fingerprint of what was deployed
python -m src.db.schema_guard show      the stored and the shipped fingerprints

The DDL is applied with IF NOT EXISTS and never altered (D-061). Deploying changed files on a database built from
older ones would leave the old tables and seeds in place without a word, and the next job would fail later, far
from the cause. The guard stores the SHA-256 of the exact deployed script (`src.db.deploy.script_for`) as a
database setting (`suva.schema_sha256`: no table, no DDL change) and compares it before every deploy:

  no schema yet                    fresh: deploy, then record
  same fingerprint                 deploy again (idempotent)
  other fingerprint                refused: back up, then reset (a human runs it; reset refuses to lose expert rows,
                                   and records the shipped fingerprint once it has deployed, so the next check is same)
  schema without fingerprint       refused, unless SUVA_SCHEMA_ADOPT=1: the operator states that the schema equals
                                   the shipped files (a database deployed before the guard existed)
"""

from __future__ import annotations

import argparse
import os
import sys

from src.db.deploy import SCHEMA_SETTING, SCHEMAS, script_for, sql_files
from src.db.pg import sha256_text

SETTING = SCHEMA_SETTING  # recorded here after a deploy, and by `src.db.deploy reset` after a fresh deploy
RESET_STEPS = (
    "back up first (make cluster-backup), then reset the schemas (docker compose run --rm migrate make db-reset: "
    "it refuses if expert rows would be lost), then make cluster-up (docs/DEPLOY.md §7)"
)


def shipped() -> str:
    """SHA-256 of the DDL script this code deploys."""
    files = sql_files()
    if not files:
        raise SystemExit("no SQL file in src/db/sql")
    return sha256_text(script_for(files))


def stored(conn) -> str | None:
    row = conn.execute(
        """SELECT split_part(cfg, '=', 2) FROM pg_db_role_setting s
           JOIN pg_database d ON d.oid = s.setdatabase AND s.setrole = 0, unnest(s.setconfig) AS cfg
           WHERE d.datname = current_database() AND split_part(cfg, '=', 1) = %s""",
        (SETTING,),
    ).fetchone()
    return row[0] if row else None


def has_schema(conn) -> bool:
    return conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)", (list(SCHEMAS),)).fetchone()[0] > 0


def decide(present: bool, recorded: str | None, current: str, adopt: bool) -> str:
    """'fresh', 'same' or 'adopt'; raises SystemExit with the steps to follow otherwise."""
    if not present:
        return "fresh"
    if recorded == current:
        return "same"
    if recorded is None:
        if adopt:
            return "adopt"
        raise SystemExit(
            "schema guard: the database holds a schema with no recorded fingerprint (deployed before the guard). "
            "If it was deployed from these exact files, set SUVA_SCHEMA_ADOPT=1 once; otherwise " + RESET_STEPS
        )
    raise SystemExit(
        f"schema guard: the database was deployed from schema {recorded[:12]}…, this image ships {current[:12]}…. "
        "The DDL is fresh-deploy only (D-061): " + RESET_STEPS
    )


def _connect(url: str | None):
    from src.db.pg import connect

    return connect(url, actor="deploy", pipeline=False)


def check(url: str | None = None) -> str:
    current = shipped()
    with _connect(url) as conn:
        state = decide(has_schema(conn), stored(conn), current, os.environ.get("SUVA_SCHEMA_ADOPT", "") == "1")
    print(f"schema guard: {state} (shipped {current[:12]}…)")
    return state


def record(url: str | None = None) -> str:
    from psycopg import sql

    current = shipped()
    with _connect(url) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        conn.execute(
            sql.SQL("ALTER DATABASE {} SET {} = {}").format(
                sql.Identifier(name), sql.SQL(SETTING), sql.Literal(current)
            )
        )
        conn.commit()
    print(f"schema guard: recorded {current[:12]}…")
    return current


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.db.schema_guard", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["check", "record", "show"])
    args = ap.parse_args(argv)
    if args.command == "check":
        check()
    elif args.command == "record":
        record()
    else:
        with _connect(None) as conn:
            print(f"stored  {stored(conn) or '-'}\nshipped {shipped()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

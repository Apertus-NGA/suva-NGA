"""Schema guard: deploy on an existing database only when its structure is the one these files build.

python -m src.db.schema_guard check    before `make db-deploy` (the cluster's migrate job); exit 1 when it differs
python -m src.db.schema_guard show     the database's structure digest against the expected one

The DDL creates tables, columns, constraints, indexes and ENUM types with IF NOT EXISTS and never alters them
(D-061): a deploy over a database built from older files would leave the old structure in place. Functions, views
and triggers are replaced by every deploy. So the guard compares the database's structure, read from its catalog
(src/db/structure.py), with expected/db/structure.json, the structure a fresh deploy of these files builds:

  no schema yet        fresh: deploy
  same structure       deploy again: functions, views and triggers are replaced, seeds add what is missing
  other structure      refused, with the differences: back up, then a human resets (docs/RUNBOOK_DB.md)

The deploy itself runs in one transaction (src/db/deploy.py): a failure leaves the database as it was.
"""

from __future__ import annotations

import argparse
import sys

from src.db import structure
from src.db.deploy import SCHEMAS

RESET_STEPS = (
    "back up first (make cluster-backup), then reset the schemas (docker compose run --rm migrate make db-reset: "
    "it refuses if expert rows would be lost), then make cluster-up (docs/RUNBOOK_DB.md)"
)


def has_schema(conn) -> bool:
    return conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)", (list(SCHEMAS),)).fetchone()[0] > 0


def decide(present: bool, live: list[str], want: list[str]) -> str:
    """'fresh' or 'same'; raises SystemExit with the first differences and the steps to follow otherwise."""
    if not present:
        return "fresh"
    if live == want:
        return "same"
    diff = "\n  ".join(structure.differences(live, want))
    raise SystemExit(
        f"schema guard: the database's structure differs from the one these files build:\n  {diff}\n"
        "The DDL never alters a table (D-061): " + RESET_STEPS
    )


def _connect(url: str | None):
    from src.db.pg import connect

    return connect(url, actor="deploy", pipeline=False)


def check(url: str | None = None) -> str:
    want = structure.expected()
    with _connect(url) as conn:
        present = has_schema(conn)
        state = decide(present, structure.read(conn) if present else [], want)
    print(f"schema guard: {state} (structure {structure.digest(want)[:12]}…)")
    return state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.db.schema_guard", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["check", "show"])
    args = ap.parse_args(argv)
    if args.command == "check":
        check()
        return 0
    want = structure.expected()
    with _connect(None) as conn:
        live = structure.read(conn) if has_schema(conn) else []
    print(f"database {structure.digest(live)[:12] if live else '-'}  ({len(live)} objects)")
    print(f"expected {structure.digest(want)[:12]}  ({len(want)} objects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

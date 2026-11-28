"""Structure of the data layer, read from the database catalog, against expected/db/structure.json.

python -m src.db.structure            compare the database (DATABASE_URL) with expected/db/structure.json; exit 1 if not
python -m src.db.structure --write    write expected/db/structure.json from the database (after a fresh deploy)

"Structure" is what a redeploy cannot change, because the DDL creates it with IF NOT EXISTS and never alters it
(D-061): tables, columns (type, nullability, default, identity), constraints, indexes and ENUM types with their
values, in the six schemas. What a redeploy replaces is left out: functions, views, triggers (constraint triggers
included), grants, seed rows, and the daily partitions of ops.log_event. So a change to a function or a view keeps
the structure; a new column, constraint, index, table or ENUM value changes it (docs/RUNBOOK_DB.md).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

from src.db.deploy import SCHEMAS
from src.db.pg import ROOT

EXPECTED = ROOT / "expected" / "db" / "structure.json"

QUERY = """
WITH rel AS (
  SELECT c.oid, n.nspname || '.' || c.relname AS name, c.relkind
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = ANY(%(schemas)s) AND c.relkind IN ('r', 'p') AND NOT c.relispartition
)
SELECT 'table' AS kind, rel.name, rel.relkind::text AS detail FROM rel
UNION ALL
SELECT 'column', rel.name || '.' || a.attname,
       format_type(a.atttypid, a.atttypmod)
       || CASE WHEN a.attnotnull THEN ' not null' ELSE '' END
       || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')
       || CASE WHEN a.attidentity <> '' THEN ' identity ' || a.attidentity::text ELSE '' END
       || CASE WHEN a.attgenerated <> '' THEN ' generated' ELSE '' END
  FROM rel JOIN pg_attribute a ON a.attrelid = rel.oid
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
 WHERE a.attnum > 0 AND NOT a.attisdropped
UNION ALL
SELECT 'constraint', rel.name || '.' || co.conname, pg_get_constraintdef(co.oid)
  FROM rel JOIN pg_constraint co ON co.conrelid = rel.oid
 WHERE co.contype <> 't'
UNION ALL
SELECT 'index', rel.name || '.' || i.relname, pg_get_indexdef(i.oid)
  FROM rel JOIN pg_index x ON x.indrelid = rel.oid JOIN pg_class i ON i.oid = x.indexrelid
UNION ALL
SELECT 'enum', n.nspname || '.' || t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace JOIN pg_enum e ON e.enumtypid = t.oid
 WHERE n.nspname = ANY(%(schemas)s)
 GROUP BY n.nspname, t.typname
ORDER BY 1, 2
"""


def read(conn) -> list[str]:
    """One line per structural object, sorted: `kind<TAB>name<TAB>definition`."""
    rows = conn.execute(QUERY, {"schemas": list(SCHEMAS)}).fetchall()
    return [f"{kind}\t{name}\t{detail}" for kind, name, detail in rows]


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def expected(path: Path = EXPECTED) -> list[str]:
    if not path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} is missing: run make db-structure WRITE=1 after a fresh deploy")
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = data["objects"]
    if digest(lines) != data["sha256"]:
        raise SystemExit(f"{path.relative_to(ROOT)}: sha256 does not match its objects (edited by hand?)")
    return lines


def write(lines: list[str], path: Path = EXPECTED) -> None:
    counts: dict[str, int] = {}
    for line in lines:
        kind = line.split("\t", 1)[0]
        counts[kind] = counts.get(kind, 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sha256": digest(lines), "counts": counts, "objects": lines}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def differences(live: list[str], want: list[str], limit: int = 8) -> list[str]:
    """The first lines that differ, `+` in the database and not expected, `-` expected and not in the database."""
    diff = difflib.unified_diff(want, live, lineterm="", n=0)
    out = [d for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---")]
    return out[:limit]


def _connect(url: str | None):
    from src.db.pg import connect

    return connect(url, actor="deploy", pipeline=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.db.structure", description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write expected/db/structure.json from the database")
    args = ap.parse_args(argv)
    with _connect(None) as conn:
        live = read(conn)
    if args.write:
        write(live)
        print(f"structure: wrote {EXPECTED.relative_to(ROOT)} ({len(live)} objects, {digest(live)[:12]}…)")
        return 0
    want = expected()
    if live == want:
        print(f"structure: the database matches {EXPECTED.relative_to(ROOT)} ({len(live)} objects)")
        return 0
    print(f"structure: the database differs from {EXPECTED.relative_to(ROOT)}:", file=sys.stderr)
    for line in differences(live, want):
        print(f"  {line}", file=sys.stderr)
    print(
        "  a structural change needs a fresh deploy, then make db-structure WRITE=1 (docs/RUNBOOK_DB.md)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

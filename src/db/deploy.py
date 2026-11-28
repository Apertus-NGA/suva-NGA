"""Deploy and test the data layer (docs/DB_DDL_PLANNING.md §15, §19). Standard library only: it runs psql.

    python -m src.db.deploy deploy            apply src/db/sql/NN_*.sql in order, in one psql session
    python -m src.db.deploy reset --yes       fresh deploy: drop the six schemas, deploy, record the fingerprint
    python -m src.db.deploy test              run tests/sql/*_test.sql, each in a transaction rolled back

Target: DATABASE_URL (or --url) with a local psql, or --compose to run psql inside the compose service `db`
(its port is not published to the host). `reset` refuses to drop state written by people (expert reviews,
expert summary versions) unless --discard-authored is given: export it first (docs/DB_DDL_PLANNING.md §14).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = Path(__file__).resolve().parent / "sql"
TEST_DIR = ROOT / "tests" / "sql"
SCHEMAS = ("summ", "gold", "triage", "corpus", "audit", "ops")
INCLUDE = re.compile(r"^\\ir\s+(\S+)\s*$", re.MULTILINE)
# The schema fingerprint setting of src/db/schema_guard.py (kept here: this module is standard library only).
SCHEMA_SETTING = "suva.schema_sha256"


def sql_files(directory: Path = SQL_DIR) -> list[Path]:
    """The numbered DDL files, in deploy order (00_ first)."""
    return sorted(p for p in directory.glob("[0-9][0-9]_*.sql") if p.is_file())


def test_files(directory: Path = TEST_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*_test.sql") if p.is_file())


def expand_includes(path: Path, seen: tuple[Path, ...] = ()) -> str:
    """Inline `\\ir file` lines, so the whole script can go through stdin (also inside a container)."""
    if path in seen:
        raise ValueError(f"include cycle: {' -> '.join(p.name for p in (*seen, path))}")
    text = path.read_text(encoding="utf-8")
    return INCLUDE.sub(lambda m: expand_includes((path.parent / m.group(1)).resolve(), (*seen, path)), text)


def script_for(files: list[Path]) -> str:
    parts = ["\\set ON_ERROR_STOP on", "SET client_min_messages = warning;"]
    for f in files:
        parts.append(f"\\echo '== {f.name}'")
        parts.append(expand_includes(f))
    return "\n".join(parts) + "\n"


def psql_command(args: argparse.Namespace) -> list[str]:
    base = ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-P", "pager=off"]
    if args.compose:
        user = os.environ.get("POSTGRES_USER", "suva")
        db = os.environ.get("POSTGRES_DB", "suva")
        return ["docker", "compose", "exec", "-T", "db", "psql", "-U", user, "-d", db, *base]
    url = args.url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("no target: set DATABASE_URL, pass --url, or use --compose")
    return ["psql", url, *base]


def run_psql(args: argparse.Namespace, script: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(psql_command(args), input=script, text=True, capture_output=capture, cwd=ROOT, check=False)


def scalar(args: argparse.Namespace, sql: str) -> str:
    res = run_psql(args, f"\\pset tuples_only on\n\\pset format unaligned\n{sql}\n", capture=True)
    if res.returncode != 0:
        raise SystemExit(f"psql failed: {res.stderr.strip()}")
    return res.stdout.strip()


def authored_rows(args: argparse.Namespace) -> int:
    """Rows a rebuild cannot recreate: expert reviews and expert summary versions."""
    present = scalar(
        args,
        "SELECT to_regclass('gold.expert_review') IS NOT NULL AND to_regclass('summ.summary_version') IS NOT NULL;",
    )
    if present != "t":
        return 0
    count = scalar(
        args,
        "SELECT (SELECT count(*) FROM gold.expert_review)"
        " + (SELECT count(*) FROM summ.summary_version WHERE creator_kind = 'expert');",
    )
    return int(count or 0)


def cmd_deploy(args: argparse.Namespace) -> int:
    files = sql_files()
    if not files:
        raise SystemExit(f"no SQL file in {SQL_DIR}")
    res = run_psql(args, script_for(files))
    print(f"deploy: {len(files)} files applied" if res.returncode == 0 else "deploy: FAILED")
    return res.returncode


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("reset drops the schemas " + ", ".join(SCHEMAS) + ": pass --yes", file=sys.stderr)
        return 2
    kept = authored_rows(args)
    if kept and not args.discard_authored:
        print(
            f"reset refused: {kept} rows written by experts would be lost. Export them first"
            " (docs/DB_DDL_PLANNING.md §14), or pass --discard-authored.",
            file=sys.stderr,
        )
        return 3
    drop = "DROP SCHEMA IF EXISTS " + ", ".join(SCHEMAS) + " CASCADE;"
    res = run_psql(args, f"\\set ON_ERROR_STOP on\nSET client_min_messages = warning;\n{drop}\n")
    if res.returncode != 0:
        return res.returncode
    print("reset: schemas dropped")
    status = cmd_deploy(args)
    if status == 0:
        status = record_fingerprint(args)
    return status


def record_fingerprint(args: argparse.Namespace) -> int:
    """After a reset: store the fingerprint of the script just deployed (src/db/schema_guard.py), so the next
    bootstrap sees the same schema. Without it the database kept the fingerprint of the schema the reset dropped,
    and the guard refused the next `make cluster-up` again, looping on its own recovery steps."""
    sha = hashlib.sha256(script_for(sql_files()).encode("utf-8")).hexdigest()  # = schema_guard.shipped()
    res = run_psql(
        args,
        "\\set ON_ERROR_STOP on\n"
        f"SELECT format('ALTER DATABASE %I SET {SCHEMA_SETTING} = %L', current_database(), '{sha}') \\gexec\n",
    )
    if res.returncode == 0:
        print(f"reset: schema fingerprint recorded ({sha[:12]}…)")
    return res.returncode


def cmd_test(args: argparse.Namespace) -> int:
    files = test_files()
    if not files:
        raise SystemExit(f"no *_test.sql in {TEST_DIR}")
    failed = []
    for f in files:
        res = run_psql(args, script_for([f]), capture=True)
        status = "ok" if res.returncode == 0 else "FAILED"
        print(f"{status:6} {f.name}")
        if res.returncode != 0:
            failed.append(f.name)
            print(res.stderr.strip(), file=sys.stderr)
    print(f"db tests: {len(files) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.db.deploy", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["deploy", "reset", "test"])
    ap.add_argument("--url", help="PostgreSQL URL (default: $DATABASE_URL)")
    ap.add_argument("--compose", action="store_true", help="run psql inside the compose service db")
    ap.add_argument("--yes", action="store_true", help="confirm reset")
    ap.add_argument("--discard-authored", action="store_true", help="reset even if expert rows exist")
    args = ap.parse_args(argv)
    return {"deploy": cmd_deploy, "reset": cmd_reset, "test": cmd_test}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

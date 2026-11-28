"""Passwords of the login roles, from the environment (src/db/sql/90_roles.sql; docs/DEPLOY.md §4).

python -m src.db.logins                  run as the owner after `make db-deploy`; idempotent
python -m src.db.logins --init-env .env  on the host: generate the cluster's missing secrets into .env
python -m src.db.logins --verify LOGIN   prove that LOGIN connects and cannot change the schema

The DDL creates three logins without a password, so none of them can log in over the network until this
runs. Each one gets the password of its variable; a login whose variable is empty or unset keeps no password and
stays unusable (never an empty password, never a default). Values are never printed or logged (G13).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

LOGINS = {
    "suva_pipeline": "SUVA_PIPELINE_PASSWORD",  # pipeline steps and loaders (group suva_g_pipeline)
    "suva_api": "SUVA_API_PASSWORD",  # the API and the UI (groups suva_g_read, suva_g_review)
    "suva_report": "SUVA_REPORT_PASSWORD",  # read-only: the report, the judges (group suva_g_read)
}
MIN_LENGTH = 16


def plan(env: dict[str, str] | None = None) -> dict[str, str | None]:
    """{login: password or None}. Refuses a password shorter than MIN_LENGTH."""
    env = dict(os.environ if env is None else env)
    out: dict[str, str | None] = {}
    for login, var in LOGINS.items():
        value = env.get(var, "").strip()
        if value and len(value) < MIN_LENGTH:
            raise SystemExit(f"{var} is shorter than {MIN_LENGTH} characters: refused")
        out[login] = value or None
    return out


def apply(passwords: dict[str, str | None], url: str | None = None) -> list[str]:
    """Set each given password (scram-sha-256, the server default). Returns the logins changed."""
    from psycopg import sql  # imported here: --init-env runs on the host, without the project's packages

    from src.db.pg import connect

    changed: list[str] = []
    with connect(url, actor="deploy", pipeline=False) as conn, conn.cursor() as cur:
        for login, password in passwords.items():
            if password is None:
                continue
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s AND rolcanlogin", (login,))
            if cur.fetchone() is None:
                raise SystemExit(f"login {login} does not exist: run make db-deploy first")
            cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
            changed.append(login)
        conn.commit()
    return changed


SCHEMAS = ("corpus", "triage", "gold", "summ", "ops", "audit")


def verify(login: str, url: str | None = None) -> list[str]:
    """Connect with the environment's credentials, check the session is `login`, and try to create a table in
    each schema. Returns the schemas where that worked (expected: none for a pipeline, API or report login)."""
    import psycopg

    from src.db.pg import connect

    allowed: list[str] = []
    with connect(url, actor="verify", pipeline=False) as conn:
        user = conn.execute("SELECT current_user").fetchone()[0]
        if user != login:
            raise SystemExit(f"connected as {user}, expected {login}")
        for schema in SCHEMAS:
            try:
                conn.execute(f'CREATE TABLE "{schema}".login_probe (x int)')
                allowed.append(schema)
            except psycopg.errors.InsufficientPrivilege:
                pass
            conn.rollback()
    return allowed


CLUSTER_SECRETS = ("POSTGRES_PASSWORD", *LOGINS.values())


def init_env(path: Path) -> list[str]:
    """Add a random value for each cluster secret that `path` lacks or leaves empty. Never overwrites a value,
    never prints one; the file is made readable by its owner only. Returns the names written."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    filled = {
        line.split("=", 1)[0].strip()
        for line in lines
        if "=" in line and not line.lstrip().startswith("#") and line.split("=", 1)[1].strip()
    }
    missing = [name for name in CLUSTER_SECRETS if name not in filled]
    if missing:
        kept = [line for line in lines if line.split("=", 1)[0].strip() not in missing]
        kept += [f"{name}={secrets.token_urlsafe(32)}" for name in missing]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.db.logins", description=__doc__.splitlines()[0])
    ap.add_argument("--init-env", type=Path, metavar="FILE", help="generate the missing cluster secrets into FILE")
    ap.add_argument("--verify", metavar="LOGIN", choices=sorted(LOGINS), help="prove LOGIN cannot change the schema")
    args = ap.parse_args(argv)
    if args.verify:
        allowed = verify(args.verify)
        if allowed:
            print(f"{args.verify} can create tables in: {', '.join(allowed)}", file=sys.stderr)
            return 1
        print(f"least privilege: {args.verify} connects and cannot create a table in {', '.join(SCHEMAS)}")
        return 0
    if args.init_env:
        written = init_env(args.init_env)
        print(f"{args.init_env}: generated {', '.join(written)}" if written else f"{args.init_env}: secrets present")
        return 0
    passwords = plan()
    changed = apply(passwords)
    skipped = [login for login, value in passwords.items() if value is None]
    print(f"logins: password set for {', '.join(changed) or 'none'}", end="")
    print(f"; no password (cannot log in): {', '.join(skipped)}" if skipped else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())

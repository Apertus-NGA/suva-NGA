"""Registry loader: step versions, their configuration schemas, rules and pipeline profiles (D-064).

Each step ships a registry file (for example src/layer1/registry/layer1_filter.json) and a pydantic model
of its configuration. Loading is idempotent and strict: a version that already exists must be identical
(configuration, code hash, rules); any change needs a new version number. docs/DB_DDL_PLANNING.md §7.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel

from src.db.pg import ROOT, uuid5

Version = tuple[int, int, int]


class RegistryConflict(RuntimeError):
    """An existing version differs from the file: bump the version instead of editing it."""


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def label(version: Sequence[int]) -> str:
    return "V{}.{}.{}".format(*version)


def code_sha256(paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(paths):
        digest.update(rel.encode("utf-8"))
        digest.update((ROOT / rel).read_bytes())
    return digest.hexdigest()


def ensure_schema(
    cur: psycopg.Cursor,
    subject: str,
    code: str,
    version: Version,
    model: type[BaseModel],
    template: dict,
    changelog: str,
) -> str:
    schema = model.model_json_schema()
    sha = _sha(schema)
    v_major, v_minor, v_patch = version
    cur.execute(
        """INSERT INTO ops.json_schema (subject, schema_code, v_major, v_minor, v_patch, json_schema, template,
                                        schema_sha256, status, bump_kind, changelog, created_by_actor)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', 'initial', %s, current_setting('app.actor', true))
           ON CONFLICT (schema_code, v_major, v_minor, v_patch) DO NOTHING""",
        (subject, code, v_major, v_minor, v_patch, json.dumps(schema), json.dumps(template), sha, changelog),
    )
    cur.execute(
        "SELECT json_schema_id, schema_sha256 FROM ops.json_schema WHERE schema_code = %s AND v_major = %s AND "
        "v_minor = %s AND v_patch = %s",
        (code, v_major, v_minor, v_patch),
    )
    sid, stored = cur.fetchone()
    if stored != sha:
        raise RegistryConflict(f"{code} {label(version)}: the pydantic model changed; bump the schema version")
    return str(sid)


def load_step_registry(
    conn: psycopg.Connection,
    path: Path,
    config_model: type[BaseModel],
    rule_model: type[BaseModel] | None,
    code_paths: Sequence[str],
) -> dict[Version, str]:
    """Load one step's registry file. Returns {version: component_version_id}."""
    reg = json.loads(path.read_text(encoding="utf-8"))
    step = reg["step"]
    code_hash = code_sha256(code_paths)
    with conn.transaction(), conn.cursor() as cur:
        cs = reg["config_schema"]
        config_schema_id = ensure_schema(
            cur,
            "step_config",
            cs["schema_code"],
            tuple(cs["version"]),
            config_model,
            reg["versions"][0]["config"],
            cs["changelog"],
        )
        rule_ids: dict[str, str] = {}
        if rule_model is not None:
            rs = reg["rule_schema"]
            rule_schema_id = ensure_schema(
                cur,
                "rule_definition",
                rs["schema_code"],
                tuple(rs["version"]),
                rule_model,
                reg["rules"][0]["definition"],
                rs["changelog"],
            )
            for rule in reg["rules"]:
                rule_model.model_validate(rule["definition"])
                v = tuple(rule["version"])
                cur.execute(
                    """INSERT INTO ops.rule (step, rule_code, v_major, v_minor, v_patch, kind, definition,
                       definition_schema_id,
                                              reason_code, description, status, bump_kind, changelog, created_by_actor)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 'initial', %s,
                           current_setting('app.actor', true))
                       ON CONFLICT (rule_code, v_major, v_minor, v_patch) DO NOTHING""",
                    (
                        step,
                        rule["rule_code"],
                        *v,
                        rule["kind"],
                        json.dumps(rule["definition"]),
                        rule_schema_id,
                        rule.get("reason_code", rule["rule_code"]),
                        rule["description"],
                        rule["changelog"],
                    ),
                )
                cur.execute(
                    "SELECT rule_id, definition, kind::text FROM ops.rule WHERE rule_code = %s AND v_major = %s AND "
                    "v_minor = %s AND v_patch = %s",
                    (rule["rule_code"], *v),
                )
                rid, definition, kind = cur.fetchone()
                if definition != rule["definition"] or kind != rule["kind"]:
                    raise RegistryConflict(
                        f"rule {rule['rule_code']} {label(v)} differs from the file; bump its version"
                    )
                rule_ids[rule["rule_code"]] = str(rid)

        ids: dict[Version, str] = {}
        for ver in reg["versions"]:
            v = tuple(ver["version"])
            config_model.model_validate(ver["config"])
            previous = uuid5("cv|{}|{}|{}|{}".format(step, *ver["previous"])) if ver.get("previous") else None
            cur.execute(
                """INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id,
                   config, config_sha256,
                                                      code_path, code_sha256, status, bump_kind, previous_version_id,
                                                          changelog,
                                                      created_by_actor)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, current_setting('app.actor',
                       true))
                   ON CONFLICT (step, v_major, v_minor, v_patch) DO NOTHING""",
                (
                    step,
                    ver["name"],
                    *v,
                    config_schema_id,
                    json.dumps(ver["config"]),
                    _sha(ver["config"]),
                    ",".join(sorted(code_paths)),
                    code_hash,
                    ver["bump_kind"],
                    previous,
                    ver["changelog"],
                ),
            )
            cvid = uuid5("cv|{}|{}|{}|{}".format(step, *v))
            cur.execute(
                "SELECT config_sha256, code_sha256 FROM ops.component_version WHERE component_version_id = %s", (cvid,)
            )
            stored_config, stored_code = cur.fetchone()
            if stored_config != _sha(ver["config"]):
                raise RegistryConflict(f"{step} {label(v)}: configuration differs from the file; bump the version")
            if stored_code != code_hash:
                raise RegistryConflict(
                    f"{step} {label(v)}: code changed ({', '.join(code_paths)}); bump the patch version"
                )
            for ordinal, code in enumerate(ver.get("rules", []), start=1):
                cur.execute(
                    """INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (cvid, rule_ids[code], ordinal),
                )
            ids[v] = cvid
    return ids


def load_profiles(conn: psycopg.Connection, path: Path) -> list[str]:
    """Load pipeline profiles: {"profiles": [{"code", "name", "is_default", "versions": [{"version", "steps"}]}]}."""
    reg = json.loads(path.read_text(encoding="utf-8"))
    loaded = []
    with conn.transaction(), conn.cursor() as cur:
        for prof in reg["profiles"]:
            cur.execute(
                """INSERT INTO ops.pipeline_profile (profile_code, name, description, is_default)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (profile_code) DO NOTHING""",
                (prof["code"], prof["name"], prof.get("description"), prof.get("is_default", False)),
            )
            for ver in prof["versions"]:
                v = tuple(ver["version"])
                previous = (
                    uuid5("profile|{}|{}|{}|{}".format(prof["code"], *ver["previous"])) if ver.get("previous") else None
                )
                cur.execute(
                    """INSERT INTO ops.pipeline_profile_version (profile_code, v_major, v_minor, v_patch, status,
                       bump_kind,
                                                                  previous_version_id, changelog, created_by_actor)
                       VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, current_setting('app.actor', true))
                       ON CONFLICT (profile_code, v_major, v_minor, v_patch) DO NOTHING""",
                    (prof["code"], *v, ver["bump_kind"], previous, ver["changelog"]),
                )
                pvid = uuid5("profile|{}|{}|{}|{}".format(prof["code"], *v))
                wanted = {step: uuid5("cv|{}|{}|{}|{}".format(step, *sv)) for step, sv in ver["steps"].items()}
                cur.execute(
                    "SELECT step::text, component_version_id::text FROM ops.pipeline_profile_step WHERE "
                    "profile_version_id = %s",
                    (pvid,),
                )
                existing = dict(cur.fetchall())
                if existing and existing != wanted:
                    raise RegistryConflict(
                        f"profile {prof['code']} {label(v)} pins other steps; add a new profile version"
                    )
                for step, cvid in wanted.items():
                    cur.execute(
                        """INSERT INTO ops.pipeline_profile_step (profile_version_id, step, component_version_id)
                           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                        (pvid, step, cvid),
                    )
                loaded.append(f"{prof['code']} {label(v)}")
    return loaded


def profile_version(cur: psycopg.Cursor, code: str = "default") -> tuple[str, str]:
    """(profile_version_id, label) of the latest active version of a profile."""
    cur.execute(
        """SELECT profile_version_id::text, version_label FROM ops.pipeline_profile_version
           WHERE profile_code = %s AND status = 'active' ORDER BY v_major DESC, v_minor DESC, v_patch DESC LIMIT 1""",
        (code,),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"no active version of profile {code}: run the registry loader")
    return row[0], row[1]


def pinned_version(cur: psycopg.Cursor, profile_version_id: str, step: str) -> str:
    cur.execute(
        "SELECT component_version_id::text FROM ops.pipeline_profile_step WHERE profile_version_id = %s AND step = %s",
        (profile_version_id, step),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"the profile version does not pin a {step} version")
    return row[0]

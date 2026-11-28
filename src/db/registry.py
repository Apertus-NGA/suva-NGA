"""Registry loader: step versions, their configuration schemas, rules and pipeline profiles (D-064).

Each step ships a registry file (for example src/layer1/registry/layer1_filter.json) and a pydantic model
of its configuration. Loading is idempotent and strict: a version that already exists must be identical
(configuration, rules, rule definitions and kinds, the decision and validation file that approved it); any
change needs a new version number. docs/DB_DDL_PLANNING.md §7.

Every version entry names the decision that approved it (`decision`, a D-NNN line of docs/DECISIONS.md) and, for a
step version, the certified expected file that validates it (`validation`, null while it has none), F-12. The
code hash a version records is the code that created it: when today's code differs (an engine fix that keeps every
certified decision, proven by the golden check), the loader prints a notice instead of refusing the version; each
run records the hash of its own run paths (params.code_sha256, F-09; a path set that can differ from the version's
code_path, src/db/runs.py). The rules bound to a version are compared too: a file that drops, reorders or
re-versions one is refused. A step version may also declare the models and prompts it uses (`models`, `prompts`:
layer2_judge); src/db/llm_registry.py binds them and compares them strictly, both ways; a step that runs code only
(CODE_ONLY_STEPS) may declare neither; any other extra key is refused.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from src.db.pg import ROOT, uuid5

Version = tuple[int, int, int]
DECISION_REF = r"^D-[0-9]{3}$"  # = ops.component_version.decision_ref CHECK
VALIDATION_REF = r"^expected/[a-z0-9_]+/[A-Za-z0-9_.-]+\.json$"  # = ops.component_version.validation_ref CHECK
PROMPT_PATH = r"^prompts/[a-z0-9_]+/[A-Za-z0-9_.-]+\.json$"  # a versioned prompt file (src/db/llm_registry.py)
# Steps that run code only: no model, no prompt (= ops.check_component_version_resource in 80_triggers.sql)
CODE_ONLY_STEPS = frozenset({"ingest", "segment", "parse", "layer1_filter", "ranking", "export"})


class RegistryConflict(RuntimeError):
    """An existing version differs from the file: bump the version instead of editing it."""


class StepVersionEntry(BaseModel):
    """One entry of `versions` in a step registry file (src/*/registry/<step>.json)."""

    model_config = ConfigDict(extra="forbid")

    version: Version
    name: str = Field(min_length=1)
    bump_kind: Literal["initial", "major", "minor", "patch"]
    previous: Version | None
    config: dict
    rules: list[str] = Field(default_factory=list, description="rule codes, in order (ordinal 1, 2, ...)")
    changelog: str = Field(min_length=1)
    decision: str = Field(pattern=DECISION_REF, description="the docs/DECISIONS.md line that approved the version")
    validation: str | None = Field(
        pattern=VALIDATION_REF, description="the certified expected file of the version; null while it has none"
    )
    models: dict[str, str] = Field(
        default_factory=dict, description="model role -> gateway id (MODELS.md); bound by src/db/llm_registry.py"
    )
    prompts: dict[str, Annotated[str, Field(pattern=PROMPT_PATH)]] = Field(
        default_factory=dict, description="prompt role -> prompt file under prompts/; bound by src/db/llm_registry.py"
    )


class ProfileVersionEntry(BaseModel):
    """One entry of `versions` of a profile in src/db/seed/profiles.json."""

    model_config = ConfigDict(extra="forbid")

    version: Version
    bump_kind: Literal["initial", "major", "minor", "patch"]
    previous: Version | None
    changelog: str = Field(min_length=1)
    steps: dict[str, Version] = Field(min_length=1)
    decision: str = Field(pattern=DECISION_REF, description="the docs/DECISIONS.md line that approved the version")


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


def _check_rule_binding(
    cur: psycopg.Cursor, step: str, version: Version, cvid: str, wanted: Sequence[tuple[str, str]]
) -> None:
    """The rules bound to a step version, in ordinal order, are exactly the file's (code and rule version).

    The binding insert is ON CONFLICT DO NOTHING, so a file that drops, reorders or re-versions a rule of an existing
    version would otherwise load without error and disagree with ops.component_version_rule.
    """
    cur.execute(
        """SELECT r.rule_code, r.version_label, b.rule_id::text FROM ops.component_version_rule b
           JOIN ops.rule r USING (rule_id) WHERE b.component_version_id = %s ORDER BY b.ordinal""",
        (cvid,),
    )
    stored = cur.fetchall()
    if [rid for _, _, rid in stored] != [rid for _, rid in wanted]:
        raise RegistryConflict(
            f"{step} {label(version)}: its rules are {[f'{c} {vl}' for c, vl, _ in stored]} in the database, "
            f"{[c for c, _ in wanted]} in the file; a version's rules are immutable (bump the version)"
        )


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
        for raw in reg["versions"]:
            ver = StepVersionEntry.model_validate(raw)
            v = ver.version
            config_model.model_validate(ver.config)
            if step in CODE_ONLY_STEPS and (ver.models or ver.prompts):
                raise RegistryConflict(f"{step} {label(v)}: a step that runs code only declares no model or prompt")
            previous = uuid5("cv|{}|{}|{}|{}".format(step, *ver.previous)) if ver.previous else None
            cur.execute(
                """INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id,
                   config, config_sha256, code_path, code_sha256, status, bump_kind, previous_version_id, changelog,
                   decision_ref, validation_ref, created_by_actor)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s,
                       current_setting('app.actor', true))
                   ON CONFLICT (step, v_major, v_minor, v_patch) DO NOTHING""",
                (
                    step,
                    ver.name,
                    *v,
                    config_schema_id,
                    json.dumps(ver.config),
                    _sha(ver.config),
                    ",".join(sorted(code_paths)),
                    code_hash,
                    ver.bump_kind,
                    previous,
                    ver.changelog,
                    ver.decision,
                    ver.validation,
                ),
            )
            cvid = uuid5("cv|{}|{}|{}|{}".format(step, *v))
            cur.execute(
                "SELECT config_sha256, code_sha256, decision_ref, validation_ref FROM ops.component_version "
                "WHERE component_version_id = %s",
                (cvid,),
            )
            stored_config, stored_code, stored_decision, stored_validation = cur.fetchone()
            if stored_config != _sha(ver.config):
                raise RegistryConflict(f"{step} {label(v)}: configuration differs from the file; bump the version")
            if (stored_decision, stored_validation) != (ver.decision, ver.validation):
                raise RegistryConflict(
                    f"{step} {label(v)}: approved by {stored_decision} / {stored_validation} in the database, "
                    f"{ver.decision} / {ver.validation} in the file; an approval is immutable (a new version, or "
                    "make db-reset for a row written before the registry carried it)"
                )
            if stored_code != code_hash:
                print(
                    f"notice: {step} {label(v)} was created by other code ({stored_code[:12]}, now {code_hash[:12]}: "
                    f"{', '.join(sorted(code_paths))}); kept, each run records its own code_sha256",
                    file=sys.stderr,
                )
            for ordinal, code in enumerate(ver.rules, start=1):
                cur.execute(
                    """INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (cvid, rule_ids[code], ordinal),
                )
            _check_rule_binding(cur, step, v, cvid, [(code, rule_ids[code]) for code in ver.rules])
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
            for raw in prof["versions"]:
                ver = ProfileVersionEntry.model_validate(raw)
                v = ver.version
                previous = uuid5("profile|{}|{}|{}|{}".format(prof["code"], *ver.previous)) if ver.previous else None
                cur.execute(
                    """INSERT INTO ops.pipeline_profile_version (profile_code, v_major, v_minor, v_patch, status,
                       bump_kind, previous_version_id, changelog, decision_ref, created_by_actor)
                       VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s, current_setting('app.actor', true))
                       ON CONFLICT (profile_code, v_major, v_minor, v_patch) DO NOTHING""",
                    (prof["code"], *v, ver.bump_kind, previous, ver.changelog, ver.decision),
                )
                pvid = uuid5("profile|{}|{}|{}|{}".format(prof["code"], *v))
                cur.execute(
                    "SELECT decision_ref FROM ops.pipeline_profile_version WHERE profile_version_id = %s", (pvid,)
                )
                stored_decision = cur.fetchone()[0]
                if stored_decision != ver.decision:
                    raise RegistryConflict(
                        f"profile {prof['code']} {label(v)}: approved by {stored_decision} in the database, "
                        f"{ver.decision} in the file; an approval is immutable (a new profile version, or make "
                        "db-reset for a row written before the seed carried it)"
                    )
                wanted = {step: uuid5("cv|{}|{}|{}|{}".format(step, *sv)) for step, sv in ver.steps.items()}
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

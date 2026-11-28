"""Registry of what an LLM step uses: models (from MODELS.md) and versioned prompt files (docs/LAYER2.md).

Kept apart from src/db/registry.py on purpose: that loader belongs to the layer-1 / platform work, this one only
adds rows next to it (docs/LAYER2_IMPLEMENTATION_PLANNING.md L2-D10). Called by `python -m src.ingest registry`
after each step registry is loaded:

- `load_models`: ops.model from the allow-list of MODELS.md, the single home of model ids (G3, DB plan §7.2);
- `load_prompt`: one prompt file under prompts/ -> ops.prompt_version;
- `bind_resources`: for every version of a step registry file that declares `"models": {role: gateway id}` or
  `"prompts": {role: path}`, the rows of ops.component_version_model and ops.component_version_prompt.

Idempotent and strict, like the step loader: a stored version must be identical, any change is a new version.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import psycopg

from src.db.pg import ROOT, sha256_file, uuid5
from src.db.registry import RegistryConflict, label
from src.llm.served_model import canonical, load_allow_list


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_models(conn: psycopg.Connection, models_md: Path = ROOT / "MODELS.md") -> dict[str, str]:
    """ops.model from the allow-list of MODELS.md: one row per model, its gateway id paired with its Hugging Face
    id. Returns {gateway_id: model_id}. Idempotent."""
    ids = load_allow_list(models_md)
    gateway = sorted(i for i in ids if "/" not in i)
    hf = {canonical(i): i for i in ids if "/" in i}
    out: dict[str, str] = {}
    digest = sha256_file(models_md)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ops.source_snapshot (source, revision, uri, file_sha256, byte_size, retrieved_at, notes)
               VALUES ('models_md', NULL, 'MODELS.md', %s, %s, now(), 'allow-list of served models (G3)')
               ON CONFLICT ON CONSTRAINT source_snapshot_uq DO NOTHING""",
            (digest, models_md.stat().st_size),
        )
        cur.execute(
            "SELECT snapshot_id::text FROM ops.source_snapshot WHERE source = 'models_md' AND file_sha256 = %s",
            (digest,),
        )
        snapshot = cur.fetchone()[0]
        for gid in gateway:
            size = re.search(r"(\d+b)$", gid)
            cur.execute(
                """INSERT INTO ops.model (gateway_id, family, size_label, hf_id, allowed, source_snapshot_id)
                   VALUES (%s, 'apertus', %s, %s, true, %s) ON CONFLICT (gateway_id) DO NOTHING""",
                (gid, size.group(1).upper() if size else "unknown", hf.get(canonical(gid)), snapshot),
            )
            out[gid] = uuid5(f"model|{gid}")
    return out


def load_prompt(cur: psycopg.Cursor, path: Path) -> str:
    """One versioned prompt file -> ops.prompt_version. Returns its id. A stored version must be identical."""
    from src.layer2.models import PromptFile  # local import: no step code at import time of the loader

    p = PromptFile.model_validate_json(path.read_text(encoding="utf-8"))
    template_sha = _sha({"system": p.system_template, "user": p.user_template, "response": p.response_schema})
    previous = uuid5("prompt|{}|{}|{}|{}".format(p.role, *p.previous)) if p.previous else None
    cur.execute(
        """INSERT INTO ops.prompt_version (role, v_major, v_minor, v_patch, template_sha256, system_template,
               user_template, response_schema, contains_suva_material, status, bump_kind, previous_version_id,
               changelog, created_by_actor)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, current_setting('app.actor', true))
           ON CONFLICT (role, v_major, v_minor, v_patch) DO NOTHING""",
        (
            p.role,
            *p.version,
            template_sha,
            p.system_template,
            p.user_template,
            json.dumps(p.response_schema) if p.response_schema is not None else None,
            p.contains_suva_material,
            p.bump_kind,
            previous,
            p.changelog,
        ),
    )
    pid = uuid5("prompt|{}|{}|{}|{}".format(p.role, *p.version))
    cur.execute("SELECT template_sha256 FROM ops.prompt_version WHERE prompt_version_id = %s", (pid,))
    if cur.fetchone()[0] != template_sha:
        raise RegistryConflict(f"prompt {p.role} {label(p.version)} differs from {path.name}; bump its version")
    return pid


def _bind(cur: psycopg.Cursor, cvid: str, table: str, key: str, wanted: dict[str, str], what: str) -> None:
    """The bindings stored for a version must equal the file's, both ways: a file that adds, changes or drops a model
    or a prompt of an existing version is refused (an empty file entry must match an empty set). A version with no
    binding yet gets the file's; the database refuses them once the version is pinned or used (t30_check)."""
    value = "model_id" if table == "ops.component_version_model" else "prompt_version_id"
    cur.execute(f"SELECT {key}::text, {value}::text FROM {table} WHERE component_version_id = %s", (cvid,))
    existing = dict(cur.fetchall())
    if existing == wanted:
        return
    if existing:
        raise RegistryConflict(f"{what}: its {table} bindings differ from the file; bump the version")
    for role, target in wanted.items():
        cur.execute(
            f"INSERT INTO {table} (component_version_id, {key}, {value}) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (cvid, role, target),
        )


def bind_resources(conn: psycopg.Connection, path: Path) -> list[str]:
    """Models and prompts of every version of one step registry file (loaded before by load_step_registry).
    Returns the versions that declare some. Every version is compared, those without `models` or `prompts` too:
    the database must then hold none for it (integration review, 28 Nov: a dropped entry passed silently)."""
    reg = json.loads(path.read_text(encoding="utf-8"))
    step, bound = reg["step"], []
    with conn.transaction(), conn.cursor() as cur:
        for ver in reg["versions"]:
            v = tuple(ver["version"])
            what = f"{step} {label(v)}"
            cvid = uuid5("cv|{}|{}|{}|{}".format(step, *v))
            cur.execute("SELECT 1 FROM ops.component_version WHERE component_version_id = %s", (cvid,))
            if cur.fetchone() is None:
                raise RegistryConflict(f"{what}: load the step registry before binding its models and prompts")
            models = {}
            for role, gid in (ver.get("models") or {}).items():
                mid = uuid5(f"model|{gid}")
                cur.execute("SELECT 1 FROM ops.model WHERE model_id = %s", (mid,))
                if cur.fetchone() is None:
                    raise RegistryConflict(f"{what}: model {gid} is not in MODELS.md's allow-list")
                models[role] = mid
            _bind(cur, cvid, "ops.component_version_model", "model_role", models, what)
            prompts = {role: load_prompt(cur, ROOT / rel) for role, rel in (ver.get("prompts") or {}).items()}
            _bind(cur, cvid, "ops.component_version_prompt", "prompt_role", prompts, what)
            if models or prompts:
                bound.append(label(v))
    return bound

"""Preset versions (summ.preset_version) from src/layer3/registry/presets/*.json (DB plan §13.2, D-064).

The preset itself (summ.preset, e.g. suva_house) is seeded by src/db/sql/95_seed_reference.sql; this loader adds its
versions, each config validated by PresetConfig and pointing to the preset_config JSON schema. Idempotent and strict,
like the step loader (src/db/registry.py): a stored version must be identical, any change is a new version. A new
version becomes the active one; the previous active version is deprecated (one active per preset, index).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg

from src.db.pg import ROOT, uuid5
from src.db.registry import RegistryConflict, ensure_schema, label
from src.layer3.models import PresetConfig, PresetVersionEntry

PRESETS_DIR = ROOT / "src" / "layer3" / "registry" / "presets"


def _sha(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def preset_version_id(code: str, version: tuple[int, int, int]) -> str:
    return uuid5("preset_version|{}|{}|{}|{}".format(code, *version))


def load_preset(conn: psycopg.Connection, path: Path) -> list[str]:
    """Load the versions of one preset file. Returns ["<code> V1.0.0", ...]."""
    reg = json.loads(path.read_text(encoding="utf-8"))
    code = reg["preset"]
    loaded = []
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT 1 FROM summ.preset WHERE preset_code = %s", (code,))
        if cur.fetchone() is None:
            raise RegistryConflict(f"preset {code} is not seeded (src/db/sql/95_seed_reference.sql): make db-deploy")
        cs = reg["config_schema"]
        schema_id = ensure_schema(
            cur,
            "preset_config",
            cs["schema_code"],
            tuple(cs["version"]),
            PresetConfig,
            reg["versions"][0]["config"],
            cs["changelog"],
        )
        for raw in reg["versions"]:
            ver = PresetVersionEntry.model_validate(raw)
            PresetConfig.model_validate(ver.config)
            pvid = preset_version_id(code, ver.version)
            cur.execute("SELECT config_sha256 FROM summ.preset_version WHERE preset_version_id = %s", (pvid,))
            row = cur.fetchone()
            if row is not None:
                if row[0] != _sha(ver.config):
                    raise RegistryConflict(f"preset {code} {label(ver.version)}: config differs; bump the version")
                loaded.append(f"{code} {label(ver.version)}")
                continue
            cur.execute(
                "UPDATE summ.preset_version SET status = 'deprecated' WHERE preset_code = %s AND status = 'active'",
                (code,),
            )
            cur.execute(
                """INSERT INTO summ.preset_version (preset_version_id, preset_code, v_major, v_minor, v_patch,
                       config_schema_id, config, config_sha256, status, bump_kind, previous_version_id, changelog,
                       created_by_actor)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, current_setting('app.actor', true))""",
                (
                    pvid,
                    code,
                    *ver.version,
                    schema_id,
                    json.dumps(ver.config),
                    _sha(ver.config),
                    ver.bump_kind,
                    preset_version_id(code, ver.previous) if ver.previous else None,
                    ver.changelog,
                ),
            )
            loaded.append(f"{code} {label(ver.version)}")
    return loaded


def load_presets(conn: psycopg.Connection, directory: Path = PRESETS_DIR) -> list[str]:
    out: list[str] = []
    for path in sorted(directory.glob("*.json")):
        out += load_preset(conn, path)
    return out


def active_preset(cur: psycopg.Cursor, code: str) -> tuple[str, str, PresetConfig] | None:
    """(preset_version_id, label, config) of the active version of a preset; None when it has none."""
    cur.execute(
        "SELECT preset_version_id::text, version_label, config FROM summ.preset_version "
        "WHERE preset_code = %s AND status = 'active'",
        (code,),
    )
    row = cur.fetchone()
    return (row[0], row[1], PresetConfig.model_validate(row[2])) if row else None

"""Ingest commands (docs/DB_DDL_PLANNING.md §8). Needs DATABASE_URL.

python -m src.ingest registry               load step versions, rules and profiles (src/*/registry, src/db/seed)
python -m src.ingest base --parquet PATH    the HF base dataset (pinned voilaj/swiss-caselaw data/bger.parquet)
python -m src.ingest gold                   Suva's labels from judgements/ (columns A-B, export links; D-051)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.pg import ROOT, connect
from src.db.registry import load_profiles, load_step_registry, pinned_version, profile_version
from src.ingest import judgements
from src.ingest.gold import load_gold
from src.ingest.hf_base import load_base
from src.ingest.models import IngestConfig
from src.layer1.models import Layer1Config, RuleDefinition

REGISTRIES = (
    ("src/ingest/registry/ingest.json", IngestConfig, None, ("src/ingest/hf_base.py", "src/ingest/models.py")),
    (
        "src/layer1/registry/layer1_filter.json",
        Layer1Config,
        RuleDefinition,
        ("src/layer1/engine.py", "src/layer1/models.py"),
    ),
)


def load_registries(conn) -> list[str]:
    loaded = []
    for path, config_model, rule_model, code in REGISTRIES:
        versions = load_step_registry(conn, ROOT / path, config_model, rule_model, code)
        loaded += [f"{path}: " + ", ".join("V{}.{}.{}".format(*v) for v in versions)]
    loaded += load_profiles(conn, ROOT / "src" / "db" / "seed" / "profiles.json")
    return loaded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry")
    base = sub.add_parser("base")
    base.add_argument("--parquet", required=True, type=Path)
    sub.add_parser("gold")
    args = ap.parse_args(argv)
    with connect(actor="ingest-cli") as conn:
        if args.cmd == "registry":
            print("\n".join(load_registries(conn)))
        elif args.cmd == "base":
            with conn.cursor() as cur:
                pvid, _ = profile_version(cur, "default")
                cur.execute(
                    "SELECT config FROM ops.component_version WHERE component_version_id = %s",
                    (pinned_version(cur, pvid, "ingest"),),
                )
                cfg = IngestConfig.model_validate(cur.fetchone()[0])
            print(
                json.dumps(load_base(conn, args.parquet, cfg, judgements.export_refs(), actor="ingest-cli"), indent=2)
            )
        else:
            print(json.dumps(load_gold(conn, actor="ingest-cli"), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

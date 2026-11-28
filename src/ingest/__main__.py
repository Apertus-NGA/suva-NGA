"""Ingest commands (docs/DB_DDL_PLANNING.md §8). Needs DATABASE_URL; runs as DB_PIPELINE_ROLE (src.db.pg).

python -m src.ingest registry               load step versions, rules and profiles (src/*/registry, src/db/seed)
python -m src.ingest base --parquet PATH    the HF base dataset (pinned voilaj/swiss-caselaw data/bger.parquet);
                                            every row of the file loaded or excluded with its reason (F-04)
python -m src.ingest gold                   Suva's labels from judgements/ (columns A-B, export links; D-051)
python -m src.ingest closure [--out PATH]   every snapshot's closure (F-04): file rows = loaded refs + exclusions,
                                            aggregates of corpus.v_ingest_closure only (no docket); exit 1 if
                                            no snapshot is loaded or one does not close
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.llm_registry import bind_resources, load_models
from src.db.pg import ROOT, connect
from src.db.registry import load_profiles, load_step_registry, pinned_version, profile_version
from src.ingest import judgements
from src.ingest.gold import load_gold
from src.ingest.hf_base import load_base
from src.ingest.models import IngestConfig
from src.layer1.models import Layer1Config, RuleDefinition
from src.layer2.models import Layer2Config

REGISTRIES = (
    ("src/ingest/registry/ingest.json", IngestConfig, None, ("src/ingest/hf_base.py", "src/ingest/models.py")),
    (
        "src/layer1/registry/layer1_filter.json",
        Layer1Config,
        RuleDefinition,
        ("src/layer1/engine.py", "src/layer1/models.py"),
    ),
    (
        "src/layer2/registry/layer2_judge.json",
        Layer2Config,
        None,
        ("src/layer2/engine.py", "src/layer2/models.py"),
    ),
)


def load_registries(conn) -> list[str]:
    models = load_models(conn)  # first: step versions bind models by id (layer2_judge)
    loaded = [f"MODELS.md: {', '.join(sorted(models))}"]
    for path, config_model, rule_model, code in REGISTRIES:
        versions = load_step_registry(conn, ROOT / path, config_model, rule_model, code)
        loaded += [f"{path}: " + ", ".join("V{}.{}.{}".format(*v) for v in versions)]
        bind_resources(conn, ROOT / path)  # models and prompts a version declares (layer2_judge), next to it
    loaded += load_profiles(conn, ROOT / "src" / "db" / "seed" / "profiles.json")
    return loaded


_CLOSURE_SQL = """
SELECT source::text, revision, file_sha256, row_count, loaded_refs, base_refs, twin_refs, exclusions,
       exclusions_by_reason, exclusions_by_row_index, unaccounted_rows, closure_ok
FROM corpus.v_ingest_closure ORDER BY source, revision, file_sha256
"""
_CLOSURE_KEYS = (
    "source",
    "revision",
    "file_sha256",
    "file_rows",
    "loaded_refs",
    "base_refs",
    "twin_refs",
    "exclusions",
    "exclusions_by_reason",
    "exclusions_by_row_index",
    "unaccounted_rows",
    "closure_ok",
)


def closure_report(conn) -> dict:
    """Per snapshot, every row of the source file accounted for (F-04): read from corpus.v_ingest_closure.

    Counts only: no docket, no external id. `closure_ok` overall = at least one snapshot and every one closes.
    """
    with conn.cursor() as cur:
        cur.execute(_CLOSURE_SQL)
        snapshots = [dict(zip(_CLOSURE_KEYS, row, strict=True)) for row in cur.fetchall()]
    conn.rollback()
    for snap in snapshots:
        snap["exclusions_by_reason"] = dict(sorted(snap["exclusions_by_reason"].items()))
    return {
        "view": "corpus.v_ingest_closure",
        "closure_ok": bool(snapshots) and all(s["closure_ok"] for s in snapshots),
        "snapshots": snapshots,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry")
    base = sub.add_parser("base")
    base.add_argument("--parquet", required=True, type=Path)
    sub.add_parser("gold")
    clo = sub.add_parser("closure")
    clo.add_argument("--out", type=Path, default=ROOT / "results" / "ingest_closure.json")
    args = ap.parse_args(argv)
    with connect(actor="ingest-cli") as conn:
        if args.cmd == "closure":
            conn.read_only = True
            report = closure_report(conn)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for snap in report["snapshots"]:
                print(
                    f"{snap['source']} {(snap['revision'] or '-')[:12]}: {snap['file_rows']} file rows = "
                    f"{snap['loaded_refs']} refs + {snap['exclusions']} exclusions "
                    f"({snap['unaccounted_rows']} unaccounted), closure_ok {snap['closure_ok']}"
                )
            if not report["snapshots"]:
                print(
                    "closure: no snapshot has refs or exclusions (load one: python -m src.ingest base)", file=sys.stderr
                )
            print(f"wrote {args.out}")
            print("closure: OK" if report["closure_ok"] else "closure: FAILED")
            return 0 if report["closure_ok"] else 1
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

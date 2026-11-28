"""Command line: uv run python -m suva_data {fetch,build,verify,dump,export,ingest,pull}

fetch   download the raw inputs into data/snapshot/ (the only step that uses the network)
build   snapshot -> PostgreSQL: load, reconcile, attach labels and gold summaries, verify, write the report
verify  re-run the checks on the existing database
dump    write data/dump/suva.sql.gz (what `docker compose up` loads from db/init/)
export  write data/tables/*.parquet + schema.sql (the same data, readable without a database)
pull    download the published snapshot + dump from Hugging Face
ingest  add the rulings published in a date range (--from/--to) or since the last ingest (--since-last);
        add-only: nothing already stored is changed (uses the network: bger.ch first, then Hugging Face
        and the mirror)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, db, export, ingest, load, verify
from . import reconcile as rec
from .loaders import gold_summaries, labels_xlsx
from .models import normalise_docket
from .sources.bger_lists import BgerListAdapter
from .sources.entscheidsuche import EntscheidsucheAdapter
from .sources.swiss_caselaw import SwissCaselawAdapter

DUMP_NAME = "suva.sql.gz"


def gold_dockets() -> frozenset[str]:
    """Rulings we need even when they were decided outside the window: those with a human summary."""
    return frozenset(d for d in (normalise_docket(p.name) for p in config.JUDGEMENTS_DIR.glob("Export_*.html")) if d)


def adapters():
    return [BgerListAdapter(), EntscheidsucheAdapter(), SwissCaselawAdapter()]


def snapshot_files() -> dict[str, dict]:
    files = {}
    for p in sorted(config.SNAPSHOT_DIR.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            rel = p.relative_to(config.SNAPSHOT_DIR).as_posix()
            files[rel] = {"sha256": h.hexdigest(), "bytes": p.stat().st_size, "source": rel.split("/", 1)[0]}
    return files


def cmd_fetch(args) -> int:
    window, extras = config.DEFAULT_WINDOW, gold_dockets()
    status = 0
    for a in adapters():
        if a.name == config.BGER_LIST and not args.include_bger:
            print(
                f"{a.name}: skipped (bger.ch refuses non-browser clients; the archived pages in the snapshot are used). Pass --include-bger to try."
            )
            continue
        try:
            written = a.fetch(window, extras)
            extra = f" status={a.last_fetch.status}" if hasattr(a, "last_fetch") and a.last_fetch else ""
            print(f"{a.name}: {len(written)} file(s) written{extra}")
        except Exception as e:  # report and continue with the other sources
            print(f"{a.name}: FAILED: {e}", file=sys.stderr)
            status = 1
    return status


def cmd_build(args) -> int:
    window = config.DEFAULT_WINDOW
    conn = db.connect()
    db.migrate(conn)
    # Rulings added by a live ingest are kept by a rebuild, although they may lie outside the window.
    extras = gold_dockets() | ingest.ingested_dockets(conn)
    run_id = db.start_run(
        conn, "build", {"window": [window.decision_from, window.decision_to], "extra_dockets": len(extras)}
    )
    try:
        # 1. snapshot manifest: what exactly are we building from?
        files = snapshot_files()
        if not files:
            raise SystemExit(f"no snapshot in {config.SNAPSHOT_DIR}: run `python -m suva_data pull` or `fetch` first")
        manifest = json.loads(config.MANIFEST_PATH.read_text()) if config.MANIFEST_PATH.exists() else None
        if manifest and not args.update_manifest:
            diffs = verify.verify_manifest_files(manifest)
            if diffs:
                print("Snapshot differs from data/manifest.json:\n  " + "\n  ".join(diffs[:40]), file=sys.stderr)
                raise SystemExit(
                    "refusing to build from a snapshot that does not match the manifest (use --update-manifest if "
                    "intended)"
                )
        by_source: dict[str, list[str]] = {}
        for rel, meta in files.items():
            by_source.setdefault(meta["source"], []).append(rel)
        for source, paths in sorted(by_source.items()):
            load.register_raw_files(conn, source, paths)

        # 2. load every source record as-is
        load_counts, list_cov = {}, None
        for a in adapters():
            load_counts[a.name] = load.load_source_records(conn, a.parse(window, extras))
            print(f"load {a.name}: {load_counts[a.name]}")
            if a.name == config.BGER_LIST:
                list_cov = a.coverage(window).as_dict()
            problems = (
                getattr(a, "problems", None)
                or getattr(a, "unparsable_dockets", None)
                or getattr(a, "undetermined", None)
            )
            if problems:
                load_counts[a.name]["adapter_problems"] = len(problems)
                print(f"  {a.name}: {len(problems)} record(s) reported as problems by the adapter", file=sys.stderr)

        # 3. reconcile (hierarchy of truth)
        report = rec.reconcile(conn, window, extras).as_dict()
        print(
            f"reconcile: {report['rulings']} rulings ({report['rulings_in_window']} in window), "
            f"{report['duplicates']} duplicates collapsed, {report['rulings_without_valid_text']} without valid text"
        )
        n_st = rec.load_statute_refs(conn, SwissCaselawAdapter().parse_statute_refs())
        report["statute_refs"] = n_st

        # 4. attach Suva's labels and gold summaries
        labels = labels_xlsx.read_labels()
        print("labels:", labels_xlsx.write_labels(conn, labels), f"dropped={len(labels.dropped)}")
        gold = gold_summaries.read_gold_summaries()
        print("gold summaries:", gold_summaries.write_gold_summaries(conn, gold))

        # 5. verify + report + manifest
        inv = verify.check_invariants(conn, expected_gold=len(gold), expected_labels=len(labels.rows), window=window)
        fp = verify.fingerprint(conn)
        config.QUALITY_REPORT_PATH.write_text(
            verify.quality_report(conn, inv, fp, load_counts, report, list_cov, labels.dropped), encoding="utf-8"
        )
        failed = [(n, d) for n, ok, d in inv if not ok]
        for name, ok, detail in inv:
            print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        print(f"fingerprint: {fp['dataset']}")
        if (
            manifest
            and manifest.get("fingerprint")
            and manifest["fingerprint"] != fp["dataset"]
            and not args.update_manifest
        ):
            failed.append(("fingerprint equals data/manifest.json", f"{fp['dataset']} != {manifest['fingerprint']}"))
            print("  [FAIL] fingerprint differs from data/manifest.json", file=sys.stderr)
        if not manifest or args.update_manifest:
            config.MANIFEST_PATH.write_text(
                json.dumps(
                    {
                        "window": {"decision_from": window.decision_from, "decision_to": window.decision_to},
                        "swiss_caselaw": {
                            "repo": config.SWISS_CASELAW_REPO,
                            "revision": config.SWISS_CASELAW_REVISION,
                            "files": config.SWISS_CASELAW_FILES,
                        },
                        "fingerprint": fp["dataset"],
                        "fingerprint_tables": fp["tables"],
                        "counts": {
                            "rulings": report["rulings"],
                            "rulings_in_window": report["rulings_in_window"],
                            "labels": len(labels.rows),
                            "gold_summaries": len(gold),
                        },
                        "files": files,
                        **(
                            {"tables": manifest["tables"]}
                            if manifest and manifest.get("tables") and manifest.get("fingerprint") == fp["dataset"]
                            else {}
                        ),
                    },
                    indent=1,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"wrote {config.MANIFEST_PATH}")
        db.finish_run(
            conn,
            run_id,
            "failed" if failed else "ok",
            {"load": load_counts, "reconcile": report, "fingerprint": fp["dataset"], "failed_checks": failed},
        )
        return 1 if failed else 0
    except BaseException as e:
        db.finish_run(conn, run_id, "failed", {"error": str(e)[:2000]})
        raise


def cmd_verify(args) -> int:
    conn = db.connect()
    gold, labels = gold_summaries.read_gold_summaries(), labels_xlsx.read_labels()
    inv = verify.check_invariants(conn, len(gold), len(labels.rows))
    for name, ok, detail in inv:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
    fp = verify.fingerprint(conn)["dataset"]
    print(f"fingerprint: {fp}")
    ok = all(o for _, o, _ in inv)
    if config.MANIFEST_PATH.exists():
        want = json.loads(config.MANIFEST_PATH.read_text()).get("fingerprint")
        same = want == fp
        print(f"  [{'ok' if same else 'FAIL'}] fingerprint equals data/manifest.json")
        ok = ok and same
    return 0 if ok else 1


def cmd_dump(args) -> int:
    """pg_dump inside the db container -> gzip (no timestamp in the gzip header, so equal content gives equal bytes)."""
    config.DUMP_DIR.mkdir(parents=True, exist_ok=True)
    out = config.DUMP_DIR / DUMP_NAME
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "pg_dump",
        "-U",
        "suva",
        "--no-owner",
        "--no-privileges",
        "--exclude-table-data=ingest_runs",
        "--restrict-key=suvadata",  # pg_dump otherwise writes a random key, so equal content would not give equal bytes
        "suva",
    ]
    proc = subprocess.Popen(cmd, cwd=config.REPO, stdout=subprocess.PIPE)
    with out.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz:
        shutil.copyfileobj(proc.stdout, gz, 1 << 20)
    if proc.wait() != 0:
        out.unlink(missing_ok=True)
        raise SystemExit("pg_dump failed (is the db container running? `docker compose up -d db`)")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def cmd_ingest(args) -> int:
    """Add the rulings published in a date range, or since the last ingest. Never changes what is already stored."""
    conn = db.connect()
    db.migrate(conn)
    if args.since_last:
        if args.published_from or args.published_to:
            raise SystemExit("give either --since-last or --from/--to, not both")
        published_from, published_to = ingest.since_last_range(conn)
    elif args.published_from and args.published_to:
        published_from, published_to = args.published_from, args.published_to
    else:
        raise SystemExit("give --since-last, or both --from and --to (publication dates, YYYY-MM-DD)")
    print(f"ingest: rulings published {published_from} .. {published_to}")
    report = ingest.ingest(conn, published_from, published_to, extra_dockets=gold_dockets())
    bger, mirror, days = report.bger, report.mirror, report.daily["days"]
    by_status = {k: sum(1 for d in days if d["status"] == k) for k in sorted({d["status"] for d in days})}
    print(f"  bger.ch lists: {bger['status']} ({bger['records']} entries for the range)")
    print(
        f"  Hugging Face daily files: {report.daily['status']} {by_status}, {report.daily['records']} rulings in the range"
    )
    print(
        f"  mirror (entscheidsuche.ch): {mirror['status']}, asked for {mirror['asked']} rulings, found {mirror['found']}"
    )
    print(
        f"  added {len(report.new_rulings)} new rulings; {report.known_rulings} were already held and left as they were"
    )
    print(f"  new rulings with two independent texts: {report.new_with_two_texts} of {len(report.new_rulings)}")
    print(f"  not yet confirmed by a bger.ch list: {report.not_confirmed_by_bger}")
    if report.text_mismatches:
        print(f"  texts differ between sources for: {', '.join(report.text_mismatches[:20])}")
    if report.kept_existing:
        print(f"  {len(report.kept_existing)} stored record(s) differ from what the source now sends (kept as stored):")
        for k in report.kept_existing[:20]:
            print(f"    {k['docket']} ({k['source']}): {', '.join(k['differs'])}")
    print(f"  status: {report.status} (run {report.run_id})")
    return 0


def cmd_export(args) -> int:
    """Parquet tables + schema.sql from the current database; their checksums go into data/manifest.json."""
    conn = db.connect()
    fp = verify.fingerprint(conn)["dataset"]
    out = export.export_tables(conn)
    for name, meta in out.items():
        print(f"  {name}: {meta.get('rows', '')} rows, {meta['bytes'] / 1e6:.1f} MB")
    if config.MANIFEST_PATH.exists():
        manifest = json.loads(config.MANIFEST_PATH.read_text())
        if manifest.get("fingerprint") != fp:
            raise SystemExit("the database does not match data/manifest.json: run `build` first, then `export`")
        manifest["tables"] = out
        config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"updated {config.MANIFEST_PATH}")
    return 0


def cmd_pull(args) -> int:
    """Download the published snapshot and dump (pinned revision) from Hugging Face."""
    from huggingface_hub import snapshot_download

    revision = args.revision or config.OWN_DATASET_REVISION
    target = config.DATA_DIR / "published"
    path = snapshot_download(config.OWN_DATASET_REPO, repo_type="dataset", revision=revision, local_dir=target)
    src = Path(path)
    if (src / "snapshot").exists():
        shutil.copytree(src / "snapshot", config.SNAPSHOT_DIR, dirs_exist_ok=True)
    if (src / "dump" / DUMP_NAME).exists():
        init = config.REPO / "db" / "init"
        init.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "dump" / DUMP_NAME, init / f"10_{DUMP_NAME}")
        print(f"dump copied to {init / ('10_' + DUMP_NAME)} (loaded by Postgres on first start)")
    print(f"pulled {config.OWN_DATASET_REPO}@{revision or 'main'} into {target}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="suva_data", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--include-bger", action="store_true")
    f.set_defaults(fn=cmd_fetch)
    b = sub.add_parser("build")
    b.add_argument("--update-manifest", action="store_true")
    b.set_defaults(fn=cmd_build)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("dump").set_defaults(fn=cmd_dump)
    sub.add_parser("export").set_defaults(fn=cmd_export)
    ing = sub.add_parser("ingest", help="add rulings by publication date; add-only")
    ing.add_argument("--from", dest="published_from", metavar="YYYY-MM-DD")
    ing.add_argument("--to", dest="published_to", metavar="YYYY-MM-DD")
    ing.add_argument("--since-last", action="store_true", help="from the last ingest (minus an overlap) to yesterday")
    ing.set_defaults(fn=cmd_ingest)
    pl = sub.add_parser("pull")
    pl.add_argument("--revision")
    pl.set_defaults(fn=cmd_pull)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

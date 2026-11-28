"""The base dataset from the pinned Hugging Face file into corpus.* (D-062, D-072; docs/DB_DDL_PLANNING.md §8.1).

Reads `voilaj/swiss-caselaw` `data/bger.parquet` at a pinned commit (a local copy, checked by SHA-256 and
recorded in ops.source_snapshot): the rulings decided in the labelled and target quarters, the target
quarter's publication population (exact HF poller dates, else first-collection approximations), and the
rulings of Suva's summary exports outside those windows. HF twin rows are dropped only when their base row
has the same date, and kept as source references. Never read: judges, clerks, outcome (D-038, D-011).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

from src.db.pg import sha256_file, sha256_text, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import begin_run, events, fail_run, finish_run, metrics
from src.ingest.judgements import DOCKET, ExportRef
from src.ingest.models import IngestConfig

_TWIN = re.compile(r"^(?P<base>.+)-D(?P<day>\d{8})$")
BGER_URL = "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://{d}-{docket}"


@dataclass
class BaseRow:
    decision_id: str
    docket: str
    decision_date: date
    language: str
    gegenstand: str | None
    legal_area: str | None
    previous_instance: str | None
    text: str | None
    publication_exact: date | None
    first_seen: date | None
    twins: list[str] = field(default_factory=list)
    populations: dict[str, str] = field(default_factory=dict)  # population code -> member basis


def _day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _filled(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def bger_url(docket: str, decision: date) -> str:
    return BGER_URL.format(d=decision.strftime("%d-%m-%Y"), docket=docket.replace("/", "-"))


def read_base(parquet: Path, cfg: IngestConfig, refs: list[ExportRef]) -> tuple[list[BaseRow], Counter]:
    """Select the base rulings from the HF file. Returns the rows and counters (read, twins, rejected)."""
    import pyarrow.parquet as pq

    lowest = min(w.start for w in cfg.decision_quarters.values())
    ref_dockets = sorted({r.docket for r in refs})
    filters = [
        [("decision_date", ">=", lowest)],
        [("publication_date", ">=", cfg.publication_exact.start)],
        [("scraped_at", ">=", cfg.publication_approx.start)],
    ]
    if ref_dockets:  # an empty "in" list has no type: pyarrow refuses it
        filters.append([("docket_number", "in", ref_dockets)])
    table = pq.read_table(parquet, columns=cfg.columns, filters=filters)
    stats: Counter = Counter(rows_read=table.num_rows)
    raw = table.to_pylist()
    by_id = {r["decision_id"]: r for r in raw}
    refs_by_key = {(r.docket, r.decision_date) for r in refs}

    rows: dict[str, BaseRow] = {}
    twins: list[tuple[str, str]] = []
    for r in raw:
        twin = _TWIN.match(r["decision_id"])
        base = by_id.get(twin.group("base")) if twin else None
        if base is not None and base["decision_date"] == r["decision_date"]:
            twins.append((r["decision_id"], base["decision_id"]))
            continue
        docket = r["docket_number"] if isinstance(r["docket_number"], str) else ""
        decided = _day(r["decision_date"])
        if decided is None:
            stats["no_decision_date"] += 1
            continue
        published = _day(r["publication_date"])
        if published is not None and published.isoformat() < cfg.poller_start:
            published = None  # not trusted before the HF poller started (crawl brief)
        row = BaseRow(
            decision_id=r["decision_id"],
            docket=docket,
            decision_date=decided,
            language=r["language"],
            gegenstand=_filled(r["title"]),
            legal_area=_filled(r["legal_area"]),
            previous_instance=_filled(r.get("appealed_court_raw")),
            text=r["full_text"] if _filled(r["full_text"]) else None,
            publication_exact=published,
            first_seen=_day(r["scraped_at"]),
        )
        day = decided.isoformat()
        for quarter, window in cfg.decision_quarters.items():
            if window.start <= day <= window.end:
                row.populations[f"{quarter}_decision"] = "decision_date"
        target = cfg.target_quarter
        exact = (
            row.publication_exact
            and cfg.publication_exact.start <= row.publication_exact.isoformat() <= cfg.publication_exact.end
        )
        approx = (
            row.publication_exact is None
            and row.first_seen is not None
            and cfg.publication_approx.start <= row.first_seen.isoformat() <= cfg.publication_approx.end
        )
        if exact or approx:
            row.populations[f"{target}_publication"] = "publication_exact" if exact else "publication_approx"
        if f"{target}_decision" in row.populations or f"{target}_publication" in row.populations:
            row.populations[f"{target}_union"] = (
                row.populations.get(f"{target}_decision") or row.populations[f"{target}_publication"]
            )
        if not row.populations and (docket, decided) in refs_by_key:
            row.populations["suva_reference"] = "reference"
        if not row.populations:
            stats["out_of_window"] += 1
        elif not DOCKET.match(docket):
            stats["rejected_malformed"] += 1  # inside a window but not a docket: counted, never silently dropped
        else:
            rows[r["decision_id"]] = row
    for twin_id, base_id in twins:
        if base_id in rows:
            rows[base_id].twins.append(twin_id)
            stats["twins"] += 1
    return list(rows.values()), stats


def population_specs(cfg: IngestConfig) -> list[tuple[str, str | None, str, str, bool]]:
    """(code, quarter, definition, role, delivery_default) of every population the loader builds."""
    t = cfg.target_quarter
    specs = [
        (f"{q}_decision", q, "decision_date", "target" if q == t else "labelled", False) for q in cfg.decision_quarters
    ]
    specs += [
        (f"{t}_publication", t, "publication_date", "target", True),
        (f"{t}_union", t, "union", "target", False),
        ("suva_reference", None, "reference", "reference", False),
    ]
    return specs


def load_base(conn: psycopg.Connection, parquet: Path, cfg: IngestConfig, refs: list[ExportRef], actor: str) -> dict:
    """Load the base dataset. Idempotent: natural keys, ON CONFLICT DO NOTHING, populations frozen once."""
    file_sha = sha256_file(parquet)
    rows, stats = read_base(parquet, cfg, refs)
    with conn.cursor() as cur:
        pvid, _ = profile_version(cur, "default")
        cvid = pinned_version(cur, pvid, "ingest")
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="ingest",
        step="ingest",
        operation="ingest.hf_base",
        component_version_id=cvid,
        params={"parquet_sha256": file_sha, "hf_revision": cfg.hf_revision},
        actor=actor,
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ops.source_snapshot (source, revision, uri, file_sha256, byte_size, row_count,
                   retrieved_at)
                   VALUES ('hf_bger', %s, %s, %s, %s, %s, now()) ON CONFLICT ON CONSTRAINT source_snapshot_uq DO
                       NOTHING""",
                (
                    cfg.hf_revision,
                    f"hf://datasets/{cfg.hf_repo}/{cfg.hf_file}@{cfg.hf_revision}",
                    file_sha,
                    parquet.stat().st_size,
                    stats["rows_read"],
                ),
            )
            cur.execute(
                "SELECT snapshot_id::text FROM ops.source_snapshot WHERE source = 'hf_bger' AND revision = %s AND "
                "file_sha256 = %s",
                (cfg.hf_revision, file_sha),
            )
            snap = cur.fetchone()[0]
            run_id = run.run_id
            cur.executemany(
                """INSERT INTO corpus.ruling (docket, decision_date, language, gegenstand, previous_instance,
                   bger_url, origin, created_by_run_id)
                   VALUES (%s, %s, %s, %s, %s, %s, 'base_dataset', %s) ON CONFLICT (docket, decision_date) DO
                       NOTHING""",
                [
                    (
                        r.docket,
                        r.decision_date,
                        r.language,
                        r.gegenstand,
                        r.previous_instance,
                        bger_url(r.docket, r.decision_date),
                        run_id,
                    )
                    for r in rows
                ],
            )
            ids = {(r.docket, r.decision_date): uuid5(f"bger|{r.docket}|{r.decision_date.isoformat()}") for r in rows}
            cur.executemany(
                """INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin)
                   VALUES ('hf_decision_id', %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                [
                    (did, ids[(r.docket, r.decision_date)], snap, did != r.decision_id)
                    for r in rows
                    for did in [r.decision_id, *r.twins]
                ],
            )
            cur.executemany(
                """INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, is_primary, snapshot_id)
                   VALUES (%s, 'hf', %s, %s, true, %s) ON CONFLICT DO NOTHING""",
                [(ids[(r.docket, r.decision_date)], r.text, sha256_text(r.text), snap) for r in rows if r.text],
            )
            cur.executemany(
                """INSERT INTO corpus.ingest_issue (ruling_id, reason_code, detail, run_id, span_id)
                   VALUES (%s, 'ING_TEXT_MISSING', '{}', %s, %s)""",
                [(ids[(r.docket, r.decision_date)], run_id, run.span_id) for r in rows if not r.text],
            )
            obs = [
                (ids[(r.docket, r.decision_date)], "hf_poller", "exact", r.publication_exact, snap)
                for r in rows
                if r.publication_exact
            ]
            obs += [
                (ids[(r.docket, r.decision_date)], "hf_first_seen", "approx_first_seen", r.first_seen, snap)
                for r in rows
                if r.publication_exact is None and r.first_seen
            ]
            cur.executemany(
                """INSERT INTO corpus.publication_observation (ruling_id, source, quality, observed_date, snapshot_id)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                obs,
            )
            cur.executemany(
                """INSERT INTO corpus.subject_observation (ruling_id, source, rubric, snapshot_id)
                   VALUES (%s, 'hf_legal_area', %s, %s) ON CONFLICT DO NOTHING""",
                [(ids[(r.docket, r.decision_date)], r.legal_area, snap) for r in rows if r.legal_area],
            )
            counts: dict[str, int] = {}
            for code, quarter, definition, role, default in population_specs(cfg):
                members = sorted(
                    (ids[(r.docket, r.decision_date)], r.populations[code]) for r in rows if code in r.populations
                )
                manifest = sha256_text("\n".join(m for m, _ in members))
                cur.execute(
                    """INSERT INTO corpus.population (code, quarter, definition, role, is_delivery_default,
                       description, built_by_run_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING""",
                    (code, quarter, definition, role, default, f"HF base dataset, {cfg.hf_revision[:8]}", run_id),
                )
                cur.execute(
                    "SELECT population_id::text, frozen_at IS NOT NULL, manifest_sha256 FROM corpus.population WHERE "
                    "code = %s",
                    (code,),
                )
                pop_id, frozen, stored = cur.fetchone()
                if frozen:
                    if stored != manifest:
                        raise RuntimeError(
                            f"population {code} is frozen with another membership ({stored[:12]} != {manifest[:12]})"
                        )
                else:
                    cur.executemany(
                        "INSERT INTO corpus.population_member (population_id, ruling_id, basis) VALUES (%s, %s, %s) "
                        "ON CONFLICT DO NOTHING",
                        [(pop_id, m, b) for m, b in members],
                    )
                    cur.execute(
                        "UPDATE corpus.population SET manifest_sha256 = %s, frozen_at = now() WHERE population_id = %s",
                        (manifest, pop_id),
                    )
                counts[code] = len(members)
            summary = {
                "rulings": len(rows),
                "texts": sum(1 for r in rows if r.text),
                "rows_read": stats["rows_read"],
                "twins": stats["twins"],
                "rejected_malformed": stats["rejected_malformed"],
                "out_of_window": stats["out_of_window"],
                "with_hf_legal_area": sum(1 for r in rows if r.legal_area),
                **{f"population_{k}": v for k, v in counts.items()},
            }
            metrics(cur, run, "ingest", summary, unit="rows")
            events(
                cur,
                run,
                "ingest",
                [
                    (
                        1,
                        "info",
                        "ingest.snapshot.loaded",
                        "HF base file read",
                        {"sha256": file_sha, "rows_read": stats["rows_read"]},
                        None,
                        None,
                    ),
                    (2, "info", "ingest.population.frozen", "populations built and frozen", counts, None, None),
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {"run_id": run.run_id, **summary}

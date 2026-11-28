"""Live ingest: add the rulings PUBLISHED in a date range to the database, without changing what is there.

    python -m suva_data ingest --from 2026-07-01 --to 2026-07-31     a chosen range
    python -m suva_data ingest --since-last                          from the last ingest (with an overlap) to yesterday

Rules (decided 27 Nov 2026):
1. Add only. A ruling that is already in the database is not added again, replaced or removed, and nothing
   attached to it (summaries, expert edits, labels, predictions) is touched. A source record that is already
   stored is never rewritten: if the same source now says something else, the difference is reported.
2. The one overwrite that can happen is the hierarchy of truth doing its job: a higher source
   (bger.ch > entscheidsuche.ch > Hugging Face) supplying a value for a field a lower source had filled.
   Empty fields may be filled by any source.
3. Ground truth first. Every run asks bger.ch for the daily lists of the range, politely, and stops at the
   first firewall block. The Hugging Face daily files are the fallback; what they supply stays marked as
   theirs, and rulings not confirmed by bger.ch are counted so a later run can confirm them.
4. Two independent texts. Hugging Face and the mirror can each be wrong, so every ruling of the range that
   has no text from entscheidsuche.ch yet is looked up there by case number. The mirror ranks above Hugging
   Face, so its text becomes the canonical one; where the two texts differ the ruling is flagged.

The whole database change of a run is one transaction: if anything refuses (for example the reconciler's
guard against deleting a ruling that carries work), nothing of the run is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

from . import config, db, load
from . import reconcile as rec
from .config import Window
from .sources.bger_lists import BgerListAdapter
from .sources.entscheidsuche import EntscheidsucheAdapter
from .sources.hf_daily import DailyFilesAdapter

DEFAULT_OVERLAP_DAYS = 14  # rulings can reach the sources days after their publication date
_ANY_DECISION_DATE = Window("0001-01-01", "9999-12-31")
_NO_DECISION_DATE = Window("9999-12-31", "0001-01-01")  # contains nothing: the mirror is asked by case number only
MIRROR_DIR = "mirror"  # under the live directory: one sub-directory per run, so no run rewrites another's files


@dataclass
class IngestReport:
    published_from: str
    published_to: str
    status: str = "ok"  # 'ok' | 'partial' (a source was blocked or a day failed; what arrived was still added)
    bger: dict = field(
        default_factory=dict
    )  # {"status": 'complete'|'blocked'|'incomplete'|'failed', "records": n, ...}
    daily: dict = field(default_factory=dict)  # {"status", "days": [...], "records": n}
    mirror: dict = field(default_factory=dict)  # {"status", "asked": n, "found": n, "other_decision_date": n, ...}
    records_read: int = 0
    new_rulings: list[dict] = field(default_factory=list)  # [{"docket", "decision_date", "publication_date"}]
    known_rulings: int = 0  # rulings of the range that were already in the database: left as they were
    kept_existing: list[dict] = field(default_factory=list)  # stored source records a source now contradicts
    not_confirmed_by_bger: int = 0  # new rulings whose publication date does not come from a bger.ch list
    new_with_two_texts: int = 0  # new rulings holding a valid text from two sources
    text_mismatches: list[str] = field(default_factory=list)  # rulings of the range whose two texts differ
    run_id: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def ingested_dockets(conn) -> frozenset[str]:
    """Case numbers added by earlier ingests: a rebuild must keep them although they may lie outside its window."""
    return frozenset(r[0] for r in conn.execute("SELECT DISTINCT docket FROM ingested_rulings"))


def last_published_to(conn) -> str | None:
    """Where "since last" starts from: the end of the last ingest, else the newest publication date held."""
    row = conn.execute(
        """SELECT max(params ->> 'published_to') FROM ingest_runs
           WHERE command = 'ingest' AND status IN ('ok', 'partial')"""
    ).fetchone()
    if row and row[0]:
        return row[0]
    row = conn.execute("SELECT max(publication_date)::text FROM rulings").fetchone()
    return row[0] if row else None


def since_last_range(conn, today: date | None = None, overlap_days: int = DEFAULT_OVERLAP_DAYS) -> tuple[str, str]:
    """(from, to) for "everything since the last ingest": it starts `overlap_days` earlier and ends yesterday."""
    last = last_published_to(conn)
    if last is None:
        raise ValueError("the database holds no ruling and no earlier ingest: give a date range instead")
    end = (today or date.today()) - timedelta(days=1)
    start = min(date.fromisoformat(last) - timedelta(days=overlap_days), end)
    return start.isoformat(), end.isoformat()


def _bger_records(bger, published_from: str, published_to: str) -> tuple[dict, list]:
    """Ask bger.ch for the lists of the range; return (what happened, the list entries we now hold for the range)."""
    info: dict = {}
    try:
        bger.fetch(Window(published_from, published_to))
        result = bger.last_fetch
        info = {"status": result.status, "requested": result.requested, "days_missing": len(result.remaining)}
        if result.blocked_on:
            info["blocked_on"] = result.blocked_on
        if result.detail:
            info["detail"] = result.detail
    except Exception as e:  # ground truth is attempted, never required
        info = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
    records = [
        r for r in bger.parse(_ANY_DECISION_DATE) if published_from <= r.record.get("list_date", "") <= published_to
    ]
    info["records"] = len(records)
    return info, records


def _register_new_files(conn, source: str, records: list, root: Path) -> None:
    """Record the checksum of every file the records came from. A file already recorded is left as it is."""
    paths = sorted({r.raw_file for r in records if r.raw_file})
    known = {r[0] for r in conn.execute("SELECT path FROM raw_files WHERE path = ANY(%s)", (paths,))}
    new = [p for p in paths if p not in known]
    if new:
        load.register_raw_files(conn, source, new, snapshot_dir=root)


def _mirror_records(conn, make_mirror, candidates: list[tuple[str, str]], live: Path, run_id: int) -> tuple[dict, list]:
    """Look up, by case number, the rulings of the range that have no mirror record yet.

    Only a hit for exactly the ruling asked about (same case number AND decision date) is used: the mirror
    can hold another decision under the same case number, and that is not a ruling of this range.
    """
    held = {
        (d, dd.isoformat())
        for d, dd in conn.execute(
            """SELECT docket, decision_date FROM source_records
               WHERE source = %s AND docket = ANY(%s) AND decision_date IS NOT NULL""",
            (config.ENTSCHEIDSUCHE, [d for d, _ in candidates]),
        )
    }
    wanted = {c for c in candidates if c not in held}
    info: dict = {"status": "complete", "asked": len(wanted), "found": 0, "other_decision_date": 0}
    if not wanted:
        return info, []
    label = f"{MIRROR_DIR}/run_{run_id}"
    dockets = frozenset(d for d, _ in wanted)
    try:
        mirror = make_mirror(live / label)
        mirror.fetch(_NO_DECISION_DATE, dockets)
        hits = list(mirror.parse(_NO_DECISION_DATE, dockets))
        info["requests"] = mirror.request_count
    except Exception as e:  # the mirror is a cross-check, never a condition for adding rulings
        return {**info, "status": "failed", "error": f"{type(e).__name__}: {e}"}, []
    records = [replace(r, raw_file=f"{label}/{r.raw_file}") for r in hits if (r.docket, r.decision_date) in wanted]
    info["found"], info["other_decision_date"] = len(records), len(hits) - len(records)
    return info, records


def ingest(
    conn,
    published_from: str,
    published_to: str,
    *,
    daily: DailyFilesAdapter | None = None,
    bger: BgerListAdapter | None = None,
    mirror: Callable[[Path], EntscheidsucheAdapter] | None = None,
    extra_dockets: frozenset[str] = frozenset(),
    window: Window = config.DEFAULT_WINDOW,
) -> IngestReport:
    """Add the rulings published in [published_from, published_to] (both included). See the module rules.

    `extra_dockets` and `window` are what the pinned dataset is built with (the reconciler needs them to
    know which rulings belong); the rulings of earlier ingests are added to them here.
    `mirror` builds the entscheidsuche.ch adapter for the directory it is given (one directory per run).
    """
    if date.fromisoformat(published_to) < date.fromisoformat(published_from):
        raise ValueError(f"the range ends before it starts: {published_from} .. {published_to}")
    daily = daily or DailyFilesAdapter(snapshot_dir=config.LIVE_DIR)
    live = Path(daily.snapshot_dir)
    mirror = mirror or (lambda root: EntscheidsucheAdapter(snapshot_dir=root))
    # lookahead 0: the lists wanted are exactly the days of the range (the adapter's window is in list days here).
    bger = bger or BgerListAdapter(snapshot_dir=live / config.BGER_LIST, lookahead_days=0)
    report = IngestReport(published_from, published_to)
    report.run_id = db.start_run(conn, "ingest", {"published_from": published_from, "published_to": published_to})
    try:
        # 1. ground truth first
        report.bger, bger_records = _bger_records(bger, published_from, published_to)
        # 2. the daily files
        fetched = daily.fetch(published_from, published_to)
        daily_records = list(daily.parse(published_from, published_to))
        report.daily = {
            "status": fetched.status,
            "days": fetched.days,
            "records": len(daily_records),
            **daily.parse_stats,
        }
        if report.bger["status"] != "complete" or fetched.status != "complete":
            report.status = "partial"

        candidates = sorted({(r.docket, r.decision_date) for r in bger_records + daily_records if r.decision_date})
        # 3. the mirror, for a second and independent text
        report.mirror, mirror_records = _mirror_records(conn, mirror, candidates, live, report.run_id)
        if report.mirror["status"] != "complete":
            report.status = "partial"

        records = bger_records + daily_records + mirror_records
        report.records_read = len(records)
        with conn.transaction():
            before = {
                (d, dd.isoformat())
                for d, dd in conn.execute(
                    "SELECT docket, decision_date FROM rulings WHERE docket = ANY(%s)", ([d for d, _ in candidates],)
                )
            }
            _register_new_files(conn, config.BGER_LIST, bger_records, Path(bger.snapshot_dir).parent)
            _register_new_files(conn, config.SWISS_CASELAW, daily_records, live)
            _register_new_files(conn, config.ENTSCHEIDSUCHE, mirror_records, live)
            load.load_source_records(conn, records, add_only=True, kept=report.kept_existing)
            new = [c for c in candidates if c not in before]
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO ingested_rulings (docket, decision_date, published_from, published_to)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    [(d, dd, published_from, published_to) for d, dd in new],
                )
            rec.reconcile(conn, window, frozenset(extra_dockets) | ingested_dockets(conn))
            in_range = conn.execute(
                """SELECT r.docket, r.decision_date::text, r.publication_date::text,
                          r.field_sources ->> 'publication_date',
                          (SELECT count(*) FROM ruling_texts t WHERE t.ruling_id = r.id AND t.bad_reason IS NULL),
                          coalesce((r.flags ->> 'text_mismatch')::boolean, false)
                   FROM rulings r JOIN unnest(%s::text[], %s::date[]) AS n (docket, decision_date)
                     ON n.docket = r.docket AND n.decision_date = r.decision_date
                   ORDER BY r.publication_date, r.docket""",
                ([d for d, _ in candidates], [dd for _, dd in candidates]),
            ).fetchall()
        added = [row for row in in_range if (row[0], row[1]) in set(new)]
        report.new_rulings = [{"docket": d, "decision_date": dd, "publication_date": pub} for d, dd, pub, *_ in added]
        report.known_rulings = len(candidates) - len(new)
        report.not_confirmed_by_bger = sum(1 for row in added if row[3] != config.BGER_LIST)
        report.new_with_two_texts = sum(1 for row in added if row[4] >= 2)
        report.text_mismatches = sorted(row[0] for row in in_range if row[5])
    except Exception as e:
        db.finish_run(conn, report.run_id, "failed", {"error": f"{type(e).__name__}: {e}"})
        raise
    summary = {**report.as_dict(), "new_rulings": len(report.new_rulings), "kept_existing": len(report.kept_existing)}
    summary["daily"] = {k: v for k, v in report.daily.items() if k != "days"}
    db.finish_run(conn, report.run_id, report.status, summary)
    return report

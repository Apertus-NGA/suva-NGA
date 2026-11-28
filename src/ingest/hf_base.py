"""The base dataset from the pinned Hugging Face file into corpus.* (D-062, D-072; docs/DB_DDL_PLANNING.md §8.1).

Reads `voilaj/swiss-caselaw` `data/bger.parquet` at a pinned commit (a local copy, checked by SHA-256 and
recorded in ops.source_snapshot): the rulings decided in the labelled and target quarters, the target
quarter's publication population (exact HF poller dates, else first-collection approximations), and the
rulings of Suva's summary exports outside those windows. HF twin rows are dropped only when their base row
has the same date, and kept as source references. Never read: judges, clerks, outcome (D-038, D-011).

Every row of the file is accounted for (F-04, G5): one pure function, `classify`, decides each row (loaded as a
ruling, loaded as a twin of one, or excluded with a reason code). `read_base` applies it to the rows the window
filter reads (the certified selection, `expected/ingest/<version>.json`); `exclusion_ledger` applies it to the
identity columns of every row of the file and records each row not loaded in corpus.ingest_exclusion, so that
ops.source_snapshot.row_count = source refs + exclusions (corpus.v_ingest_closure), checked before commit.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import psycopg

from src.db.pg import sha256_file, sha256_text, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import Run, begin_run, events, fail_run, finish_run, metrics
from src.ingest.judgements import DOCKET, ExportRef
from src.ingest.models import IngestConfig

_TWIN = re.compile(r"^(?P<base>.+)-D(?P<day>\d{8})$")
BGER_URL = "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://{d}-{docket}"
CODE_PATHS = ("src/ingest/hf_base.py", "src/ingest/models.py")  # recorded per run (params.code_sha256, F-09)
SOURCE = "hf_decision_id"
# The columns that decide whether a row is loaded: the exclusion ledger reads only these, for every row of the file.
IDENTITY_COLUMNS = ("decision_id", "docket_number", "decision_date", "publication_date", "scraped_at")
# Every reason a row of the file is not loaded (ops.reason_code, domain ingest, and OUT_OF_WINDOW).
EXCLUSION_REASONS = (
    "OUT_OF_WINDOW",
    "ING_TWIN_SAME_DATE",
    "ING_DECISION_DATE_MISSING",
    "ING_DOCKET_MALFORMED",
    "ING_SOURCE_ID_MISSING",
    "ING_SOURCE_ID_DUPLICATE",
)


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


@dataclass(frozen=True)
class Exclusion:
    """One row of the file that is not loaded, and why: a row of corpus.ingest_exclusion (F-04)."""

    row: int  # index of the row in the file
    external_id: str  # the HF decision_id, or row:<index> when the row has no usable id
    docket_raw: str | None
    decision_date: date | None
    reason_code: str
    detail: dict  # the identity values the decision compared; never ruling text


@dataclass
class Classified:
    """What `classify` decided, row by row: the rows loaded (twins attached to their base), the rows excluded.

    `loaded_at` maps the index of every row loaded to its id (a base row, or a twin attached to one), `attached` the
    index of every attached twin to its base id; every other row is an exclusion. `stats` holds read_base's counters.
    """

    rows: dict[str, BaseRow]
    exclusions: list[Exclusion]
    stats: Counter
    loaded_at: dict[int, str] = field(default_factory=dict)
    attached: dict[int, str] = field(default_factory=dict)

    def loaded_ids(self) -> set[str]:
        return {i for r in self.rows.values() for i in (r.decision_id, *r.twins)}


@dataclass(frozen=True)
class Ledger:
    """Every row of the file accounted for: the ids loaded and the rows excluded (file_rows = loaded + excluded)."""

    file_rows: int
    rows_read: int  # rows the window filter reads (read_base's rows_read)
    loaded_ids: frozenset[str]
    exclusions: tuple[Exclusion, ...]

    def by_reason(self) -> dict[str, int]:
        counts = Counter(e.reason_code for e in self.exclusions)
        return {code: counts.get(code, 0) for code in EXCLUSION_REASONS}


def _day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _iso(value: object) -> str | None:
    day = _day(value)
    return day.isoformat() if day else None


def _filled(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def bger_url(docket: str, decision: date) -> str:
    return BGER_URL.format(d=decision.strftime("%d-%m-%Y"), docket=docket.replace("/", "-"))


def window_filters(cfg: IngestConfig, refs: Iterable[ExportRef]) -> list[list[tuple]]:
    """The row filter of read_base (pyarrow DNF: an OR of conditions): every row that can belong to a population.

    A decision quarter needs a decision date on or after the lowest quarter start, the publication windows a
    publication or first-collection date on or after their start, a Suva export its docket. `exclusion_ledger`
    proves no row outside it is in a population.
    """
    lowest = min(w.start for w in cfg.decision_quarters.values())
    ref_dockets = sorted({r.docket for r in refs})
    filters = [
        [("decision_date", ">=", lowest)],
        [("publication_date", ">=", cfg.publication_exact.start)],
        [("scraped_at", ">=", cfg.publication_approx.start)],
    ]
    if ref_dockets:  # an empty "in" list has no type: pyarrow refuses it
        filters.append([("docket_number", "in", ref_dockets)])
    return filters


def _seen(r: dict) -> dict:
    """The dates a window compares, as the row gives them (days; None when absent or unreadable)."""
    return {
        "decision_date": _iso(r.get("decision_date")),
        "publication_date": _iso(r.get("publication_date")),
        "first_seen": _iso(r.get("scraped_at")),
    }


def _exclusion(pos: int, external_id: str, r: dict, reason: str, detail: dict) -> Exclusion:
    docket = r.get("docket_number")
    return Exclusion(
        row=pos,
        external_id=external_id,
        docket_raw=docket if isinstance(docket, str) else None,
        decision_date=_day(r.get("decision_date")),
        reason_code=reason,
        detail=detail,
    )


def classify(
    raw: Sequence[dict], cfg: IngestConfig, refs: Iterable[ExportRef], positions: Sequence[int] | None = None
) -> Classified:
    """Decide every row given: loaded (a ruling, or a same-date twin of one) or excluded with its reason. Pure.

    The certified rules (expected/ingest/<version>.json): a row whose id ends in -DYYYYMMDD is a twin when its base
    row, among the rows given, has the same raw decision date, and is kept as a source reference of that base when
    the base is loaded (ING_TWIN_SAME_DATE otherwise, detail.base_reason naming why the base is not loaded; a twin of
    a loaded base that the window filter does not read is the other ING_TWIN_SAME_DATE case, `exclusion_ledger`);
    a row needs a decision date (ING_DECISION_DATE_MISSING), a
    population (a decision quarter, the target quarter's publication window, or a Suva export; OUT_OF_WINDOW) and a
    Federal Court docket (ING_DOCKET_MALFORMED). A row without a usable id, or repeating the id of an earlier row,
    cannot be referenced: it is excluded by its index, as row:<index> (ING_SOURCE_ID_MISSING, ING_SOURCE_ID_DUPLICATE).

    `positions` are the rows' indices in the file (default: 0..n-1). `stats` holds read_base's counters, unchanged
    (rows_read, twins, no_decision_date, out_of_window, rejected_malformed): every other outcome is an exclusion.
    """
    positions = range(len(raw)) if positions is None else positions
    refs_by_key = {(r.docket, r.decision_date) for r in refs}
    stats: Counter = Counter(rows_read=len(raw))
    exclusions: list[Exclusion] = []
    by_id: dict[str, dict] = {}
    first_row: dict[str, int] = {}
    usable: list[tuple[int, dict]] = []
    for pos, r in zip(positions, raw, strict=True):
        did = r.get("decision_id")
        if not isinstance(did, str) or not did.strip():
            detail = {"decision_id": did if isinstance(did, str) else None, **_seen(r)}
            exclusions.append(_exclusion(pos, f"row:{pos}", r, "ING_SOURCE_ID_MISSING", detail))
        elif did in first_row:
            detail = {"decision_id": did, "first_row": first_row[did], **_seen(r)}
            exclusions.append(_exclusion(pos, f"row:{pos}", r, "ING_SOURCE_ID_DUPLICATE", detail))
        else:
            first_row[did] = pos
            by_id[did] = r
            usable.append((pos, r))

    rows: dict[str, BaseRow] = {}
    excluded: dict[str, str] = {}  # decision_id -> reason, named by the twins of an excluded base
    twins: list[tuple[int, dict, str]] = []
    for pos, r in usable:
        did = r["decision_id"]
        twin = _TWIN.match(did)
        base = by_id.get(twin.group("base")) if twin else None
        if base is not None and base["decision_date"] == r["decision_date"]:
            twins.append((pos, r, base["decision_id"]))
            continue
        docket = r["docket_number"] if isinstance(r["docket_number"], str) else ""
        decided = _day(r["decision_date"])
        if decided is None:
            stats["no_decision_date"] += 1
            raw_date = r["decision_date"]
            detail = {"decision_date_raw": raw_date[:40] if isinstance(raw_date, str) else None, **_seen(r)}
            exclusions.append(_exclusion(pos, did, r, "ING_DECISION_DATE_MISSING", detail))
            excluded[did] = "ING_DECISION_DATE_MISSING"
            continue
        published = _day(r["publication_date"])
        if published is not None and published.isoformat() < cfg.poller_start:
            published = None  # not trusted before the HF poller started (crawl brief)
        row = BaseRow(
            decision_id=did,
            docket=docket,
            decision_date=decided,
            language=r.get("language"),
            gegenstand=_filled(r.get("title")),
            legal_area=_filled(r.get("legal_area")),
            previous_instance=_filled(r.get("appealed_court_raw")),
            text=r.get("full_text") if _filled(r.get("full_text")) else None,
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
            exclusions.append(_exclusion(pos, did, r, "OUT_OF_WINDOW", _seen(r)))
            excluded[did] = "OUT_OF_WINDOW"
        elif not DOCKET.match(docket):
            stats["rejected_malformed"] += 1  # inside a window but not a docket: counted, never silently dropped
            detail = {"populations": sorted(row.populations), **_seen(r)}
            exclusions.append(_exclusion(pos, did, r, "ING_DOCKET_MALFORMED", detail))
            excluded[did] = "ING_DOCKET_MALFORMED"
        else:
            rows[did] = row
    loaded_at = {first_row[did]: did for did in rows}
    attached: dict[int, str] = {}
    for pos, r, base_id in twins:
        if base_id in rows:
            rows[base_id].twins.append(r["decision_id"])
            stats["twins"] += 1
            loaded_at[pos] = r["decision_id"]
            attached[pos] = base_id
        else:  # its base is not loaded: before F-04 this row was lost without a count
            reason = {"base_reason": excluded[base_id]} if base_id in excluded else {}
            exclusions.append(
                _exclusion(pos, r["decision_id"], r, "ING_TWIN_SAME_DATE", {"base_id": base_id, **reason, **_seen(r)})
            )
    return Classified(rows, exclusions, stats, loaded_at=loaded_at, attached=attached)


def read_base(parquet: Path, cfg: IngestConfig, refs: list[ExportRef]) -> tuple[list[BaseRow], Counter]:
    """Select the base rulings from the HF file. Returns the rows and counters (read, twins, rejected)."""
    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=cfg.columns, filters=window_filters(cfg, refs))
    result = classify(table.to_pylist(), cfg, refs)
    return list(result.rows.values()), result.stats


def exclusion_ledger(parquet: Path, cfg: IngestConfig, refs: list[ExportRef]) -> Ledger:
    """Every row of the file not loaded, with its reason (F-04). Reads the identity columns of all rows, no filter.

    Two applications of `classify`. On the rows the window filter reads, it decides what is loaded, exactly as in
    read_base (same function, same rows, same order: the certified selection). On every row of the file at once, it
    gives each row not loaded its reason, so that a twin is matched with its same-date base whichever of the two the
    filter reads. A row the whole-file reading would load and the certified selection does not is refused (the filter
    would lose a ruling), except a twin of a loaded base the filter does not read. That twin is the second case of
    ING_TWIN_SAME_DATE (a same-date duplicate row of the source that is not a source ref): the ruling is loaded through
    its base, but the certified selection (read_base, frozen) never sees the twin, so its id is not one of the ruling's
    source refs; detail says so (`base_loaded: true`, `why: twin_not_read`), where the first case names the base's
    own reason (`base_reason`). An exclusion whose id is taken by a loaded row is a duplicate, recorded by its index.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=list(IDENTITY_COLUMNS))
    table = table.append_column("__row", pa.array(range(table.num_rows), type=pa.int64()))
    selected = table.filter(pq.filters_to_expression(window_filters(cfg, refs)))
    read = classify(selected.to_pylist(), cfg, refs, positions=selected["__row"].to_pylist())
    raw = table.to_pylist()
    whole = classify(raw, cfg, refs, positions=table["__row"].to_pylist())
    reasons = {e.row: e for e in whole.exclusions}
    loaded = set(read.loaded_at.values())
    loaded_pos = {did: pos for pos, did in read.loaded_at.items()}
    lost = sorted(pos for pos in whole.loaded_at if pos not in read.loaded_at and pos not in whole.attached)
    if lost:
        raise RuntimeError(f"{len(lost)} rows in a population are not read by the window filter: it would lose them")
    exclusions: list[Exclusion] = []
    used = set(loaded)
    for pos in range(table.num_rows):
        if pos in read.loaded_at:
            continue
        e = reasons.get(pos)
        if e is None:  # a twin the whole file attaches to a loaded base, but the filter does not read it
            base_id = whole.attached[pos]
            if base_id not in loaded:  # `lost` above refuses a whole-file load the certified selection lacks
                raise RuntimeError(
                    f"twin {raw[pos]['decision_id']}: its base {base_id} is loaded by the whole file only"
                )
            detail = {"base_id": base_id, "base_loaded": True, "why": "twin_not_read", **_seen(raw[pos])}
            e = _exclusion(pos, raw[pos]["decision_id"], raw[pos], "ING_TWIN_SAME_DATE", detail)
        if e.external_id in used:  # its id is a loaded row's (the certified selection kept another occurrence)
            detail = {**e.detail, "decision_id": e.external_id, "first_row": loaded_pos.get(e.external_id)}
            e = replace(e, external_id=f"row:{pos}", reason_code="ING_SOURCE_ID_DUPLICATE", detail=detail)
        used.add(e.external_id)
        exclusions.append(e)
    if len(loaded) + len(exclusions) != table.num_rows:
        raise RuntimeError(
            f"classification lost rows: {table.num_rows} in the file, {len(loaded)} loaded + {len(exclusions)} excluded"
        )
    return Ledger(
        file_rows=table.num_rows,
        rows_read=selected.num_rows,
        loaded_ids=frozenset(loaded),
        exclusions=tuple(exclusions),
    )


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


def _record_exclusions(
    cur: psycopg.Cursor, snapshot_id: str, ledger: Ledger, component_version_id: str, run: Run
) -> None:
    """COPY the exclusions into a temporary table, then insert them (idempotent: ON CONFLICT DO NOTHING)."""
    cur.execute(
        """CREATE TEMPORARY TABLE ingest_exclusion_in (external_id text NOT NULL, docket_raw text, decision_date date,
           reason_code text NOT NULL, detail jsonb NOT NULL) ON COMMIT DROP"""
    )
    with cur.copy(
        "COPY pg_temp.ingest_exclusion_in (external_id, docket_raw, decision_date, reason_code, detail) FROM STDIN"
    ) as copy:
        for e in ledger.exclusions:
            copy.write_row((e.external_id, e.docket_raw, e.decision_date, e.reason_code, json.dumps(e.detail)))
    cur.execute(
        """INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date,
           reason_code, detail, component_version_id, run_id)
           SELECT %s, %s, external_id, docket_raw, decision_date, reason_code, detail, %s, %s
           FROM pg_temp.ingest_exclusion_in ORDER BY external_id
           ON CONFLICT DO NOTHING""",
        (snapshot_id, SOURCE, component_version_id, run.run_id),
    )


def _check_closure(cur: psycopg.Cursor, snapshot_id: str, ledger: Ledger) -> dict:
    """Before commit: every row of the file is a source ref or an exclusion (corpus.v_ingest_closure), as computed."""
    cur.execute(
        """SELECT row_count, loaded_refs, exclusions, unaccounted_rows, closure_ok, exclusions_by_reason
           FROM corpus.v_ingest_closure WHERE snapshot_id = %s""",
        (snapshot_id,),
    )
    found = cur.fetchone()
    if found is None:
        raise RuntimeError(f"ingest closure: snapshot {snapshot_id} has no source ref and no exclusion")
    row_count, refs, excluded, unaccounted, ok, by_reason = found
    computed = {code: n for code, n in ledger.by_reason().items() if n}
    if not ok or refs != len(ledger.loaded_ids) or excluded != len(ledger.exclusions) or by_reason != computed:
        raise RuntimeError(
            f"ingest closure failed for snapshot {snapshot_id}: {row_count} file rows, {refs} source refs + {excluded} "
            f"exclusions ({unaccounted} unaccounted); this run computed {len(ledger.loaded_ids)} loaded + "
            f"{len(ledger.exclusions)} excluded {computed} (F-04)"
        )
    return {"file_rows": row_count, "source_refs": refs, "exclusions": excluded}


def load_base(conn: psycopg.Connection, parquet: Path, cfg: IngestConfig, refs: list[ExportRef], actor: str) -> dict:
    """Load the base dataset. Idempotent: natural keys, ON CONFLICT DO NOTHING, populations frozen once.

    Every row of the file is accounted for before commit (F-04): loaded as a source ref, or recorded in
    corpus.ingest_exclusion with its reason; otherwise the run fails and nothing is written. Two loads of the same
    snapshot run one after the other (corpus.lock_source_rows, held until commit).
    """
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
        code_paths=CODE_PATHS,
        actor=actor,
    )
    try:
        ledger = exclusion_ledger(parquet, cfg, refs)
        loaded = {i for r in rows for i in (r.decision_id, *r.twins)}
        if ledger.loaded_ids != loaded or ledger.rows_read != stats["rows_read"]:
            raise RuntimeError(
                f"the exclusion ledger disagrees with read_base: {len(ledger.loaded_ids)} ids loaded and "
                f"{ledger.rows_read} rows read, read_base {len(loaded)} and {stats['rows_read']}"
            )
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
                    ledger.file_rows,
                ),
            )
            cur.execute(
                "SELECT snapshot_id::text, row_count FROM ops.source_snapshot WHERE source = 'hf_bger' "
                "AND revision = %s AND file_sha256 = %s",
                (cfg.hf_revision, file_sha),
            )
            snap, row_count = cur.fetchone()
            # one load of a snapshot at a time, until commit: the closure check below never counts another load's rows
            cur.execute("SELECT corpus.lock_source_rows(%s)", (snap,))
            if row_count != ledger.file_rows:
                raise RuntimeError(
                    f"snapshot {snap} records {row_count} rows, the file has {ledger.file_rows}: it was recorded by an "
                    "earlier loader (row_count = rows read, before F-04); rebuild the database (make db-reset)"
                )
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
            _record_exclusions(cur, snap, ledger, cvid, run)
            closure = _check_closure(cur, snap, ledger)
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
                # F-04: the whole file (existing counters above keep their meaning: rows the window filter reads)
                **closure,
                **{f"excluded_{code.lower()}": n for code, n in ledger.by_reason().items()},
                "closure_ok": 1,
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
                        {"sha256": file_sha, "rows_read": stats["rows_read"], "file_rows": ledger.file_rows},
                        None,
                        None,
                    ),
                    (2, "info", "ingest.population.frozen", "populations built and frozen", counts, None, None),
                    (
                        3,
                        "info",
                        "ingest.exclusions.recorded",
                        "every row of the file accounted for: a source ref, or an exclusion with its reason (F-04)",
                        {**closure, "by_reason": ledger.by_reason(), "closure_ok": True},
                        None,
                        None,
                    ),
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {"run_id": run.run_id, **summary}

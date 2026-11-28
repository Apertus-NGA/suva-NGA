"""The bger.ch Neuheiten pages (the court's daily "new rulings" lists) into publication and subject observations.

Reads a folder of `YYYYMMDD.html` pages (the pinned copy of the private HF dataset `suva-nga/bger-rulings`,
`snapshot/bger_list/`, under data/derived/, git-ignored) with the existing parser (src/suva_data/sources/bger_lists.py).
Each entry of a page is one source row, identified by its bger.ch `aza://` id (source `aza_id`). One
ops.source_snapshot per import (kind `bger_neuheiten`): revision = the HF dataset revision, file_sha256 = the SHA-256
of the sorted "name sha256" lines of every page file, row_count = the entries parsed.

Every entry is accounted for (F-04, G5), decided by one pure function, `classify`:
- matched to corpus.ruling on (docket, decision date): a source ref, an exact `neuheiten` publication observation
  (observed date = the page date, with the star and the Sachgebiet) and a `neuheiten` subject observation (the rubric
  and the star);
- otherwise an exclusion with an existing ingest reason (OUT_OF_WINDOW when the ruling is in none of the windows of the
  pinned ingest version, ING_SOURCE_ID_MISSING/_DUPLICATE, ING_DOCKET_MALFORMED, ING_DECISION_DATE_MISSING);
- an entry in a window but missing from the corpus has no reason code yet (seed request: ING_NOT_IN_BASE): it is
  counted (`not_in_base`), never written, and the closure is reported as not ok.

One transaction; idempotent (natural keys, ON CONFLICT DO NOTHING): a second run adds nothing but its own run row.
The page's subject line (Gegenstand) is not stored: corpus.subject_observation has no column for it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

from src.db.pg import sha256_file, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import Run, begin_run, events, fail_run, finish_run, metrics
from src.ingest.models import IngestConfig
from src.suva_data.models import DOCKET_RE, normalise_docket
from src.suva_data.sources.bger_lists import BLOCK_MARKER, parse_day

HF_REPO = "suva-nga/bger-rulings"
HF_REVISION = "7eb6025dcac351e426a0fcae1cba3a02c332e7ed"
HF_FOLDER = "snapshot/bger_list"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "replay" / "bger_neuheiten"  # committed copy of the HF folder HF_FOLDER at HF_REVISION (D-106)
SNAPSHOT_KIND = "bger_neuheiten"
SOURCE = "aza_id"
CODE_PATHS = ("src/ingest/neuheiten.py", "src/suva_data/sources/bger_lists.py")  # params.code_sha256, F-09
EXCLUSION_REASONS = (
    "OUT_OF_WINDOW",
    "ING_SOURCE_ID_MISSING",
    "ING_SOURCE_ID_DUPLICATE",
    "ING_DOCKET_MALFORMED",
    "ING_DECISION_DATE_MISSING",
)
_FILE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})\.html$")
_AZA_RE = re.compile(r"aza://([^&\"\s]+)")


@dataclass(frozen=True)
class PageRow:
    """One entry of one page, in file order (`index` counts entries across all pages)."""

    index: int
    file: str
    list_date: date
    aza_id: str | None
    case: str
    docket: str | None
    decision_date: date | None
    starred: bool
    area: str


@dataclass(frozen=True)
class Pages:
    rows: tuple[PageRow, ...]
    manifest_sha256: str
    byte_size: int
    files: int
    pages_with_list: int


@dataclass
class Classified:
    loaded: list[PageRow] = field(default_factory=list)  # matched to a ruling: written
    exclusions: list[tuple[PageRow, str, str, dict]] = field(default_factory=list)  # (row, external_id, reason, detail)
    not_in_base: list[PageRow] = field(default_factory=list)  # in a window, not in the corpus: no reason code yet

    def by_reason(self) -> dict[str, int]:
        counts = Counter(reason for _, _, reason, _ in self.exclusions)
        return {code: counts[code] for code in EXCLUSION_REASONS if counts[code]}


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if len(value) == 10 else None
    except ValueError:
        return None


def read_pages(directory: Path) -> Pages:
    """Parse every page of the folder. A file that is not YYYYMMDD.html, a firewall page, or a page whose own list
    date differs from its file name stops the import: its entries could not be accounted for."""
    files = sorted(p for p in Path(directory).iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise FileNotFoundError(f"no Neuheiten page in {directory}")
    manifest, rows, size, with_list = [], [], 0, 0
    for path in files:
        m = _FILE_RE.match(path.name)
        if not m or _day("-".join(m.groups())) is None:
            raise ValueError(f"unexpected file in the Neuheiten folder: {path.name}")
        manifest.append(f"{path.name} {sha256_file(path)}")
        size += path.stat().st_size
        page = path.read_text(encoding="utf-8")
        if not page.strip():
            continue  # a day without a list (weekends): no entry
        if BLOCK_MARKER in page:
            raise ValueError(f"{path.name} is a firewall block page, not a list")
        day = "-".join(m.groups())
        list_date, entries = parse_day(page)
        if list_date != day:
            raise ValueError(f"{path.name}: the page lists {list_date}, not {day}")
        with_list += 1
        for e in entries:
            aza = _AZA_RE.search(e.url)
            docket = normalise_docket(e.case)
            rows.append(
                PageRow(
                    index=len(rows),
                    file=path.name,
                    list_date=date.fromisoformat(day),
                    aza_id=f"aza://{aza.group(1)}" if aza else None,
                    case=e.case,
                    docket=docket if docket and DOCKET_RE.match(docket) else None,
                    decision_date=_day(e.decision_date),
                    starred=e.starred,
                    area=e.area,
                )
            )
    sha = hashlib.sha256("\n".join(sorted(manifest)).encode("utf-8")).hexdigest()
    return Pages(tuple(rows), sha, size, len(files), with_list)


def in_window(row: PageRow, cfg: IngestConfig) -> bool:
    """The windows of the pinned ingest version: a decision quarter, or a publication date in the target quarter."""
    d = row.decision_date.isoformat() if row.decision_date else None
    if d and any(w.start <= d <= w.end for w in cfg.decision_quarters.values()):
        return True
    p = row.list_date.isoformat()
    return cfg.publication_approx.start <= p <= cfg.publication_exact.end


def classify(rows: tuple[PageRow, ...], corpus_keys: set[tuple[str, date]], cfg: IngestConfig) -> Classified:
    """Decide every entry: loaded (matched on docket and decision date), excluded with its reason, or not_in_base."""
    out, seen = Classified(), {}
    for r in rows:
        detail = {"file": r.file, "list_date": r.list_date.isoformat(), "case": r.case}
        if r.decision_date:
            detail["decision_date"] = r.decision_date.isoformat()
        if r.aza_id is None:
            out.exclusions.append((r, f"row:{r.index}", "ING_SOURCE_ID_MISSING", detail))
            continue
        if r.aza_id in seen:
            detail = {**detail, "aza_id": r.aza_id, "first_row": seen[r.aza_id]}
            out.exclusions.append((r, f"row:{r.index}", "ING_SOURCE_ID_DUPLICATE", detail))
            continue
        seen[r.aza_id] = r.index
        if r.docket is None:
            out.exclusions.append((r, r.aza_id, "ING_DOCKET_MALFORMED", detail))
        elif r.decision_date is None:
            out.exclusions.append((r, r.aza_id, "ING_DECISION_DATE_MISSING", detail))
        elif (r.docket, r.decision_date) in corpus_keys:
            out.loaded.append(r)
        elif in_window(r, cfg):
            out.not_in_base.append(r)
        else:
            windows = {q: [w.start, w.end] for q, w in cfg.decision_quarters.items()}
            windows["publication"] = [cfg.publication_approx.start, cfg.publication_exact.end]
            out.exclusions.append((r, r.aza_id, "OUT_OF_WINDOW", {**detail, "windows": windows}))
    if len(out.loaded) + len(out.exclusions) + len(out.not_in_base) != len(rows):
        raise RuntimeError("classification lost rows")
    return out


def _corpus_keys(cur: psycopg.Cursor) -> set[tuple[str, date]]:
    cur.execute("SELECT docket, decision_date FROM corpus.ruling")
    return {(d, dd) for d, dd in cur.fetchall()}


def _pinned_config(cur: psycopg.Cursor) -> tuple[str, str, IngestConfig]:
    pvid, _ = profile_version(cur, "default")
    cvid = pinned_version(cur, pvid, "ingest")
    cur.execute("SELECT config FROM ops.component_version WHERE component_version_id = %s", (cvid,))
    return pvid, cvid, IngestConfig.model_validate(cur.fetchone()[0])


def _counts(pages: Pages, c: Classified) -> dict:
    return {
        "files": pages.files,
        "pages_with_list": pages.pages_with_list,
        "rows_in": len(pages.rows),
        "matched": len(c.loaded),
        "excluded": dict(c.by_reason()),
        "not_in_base": len(c.not_in_base),
    }


def dry_run(conn: psycopg.Connection, directory: Path) -> dict:
    """Classify without writing anything."""
    pages = read_pages(directory)
    with conn.cursor() as cur:
        _, _, cfg = _pinned_config(cur)
        c = classify(pages.rows, _corpus_keys(cur), cfg)
    return {"dry_run": True, "manifest_sha256": pages.manifest_sha256, **_counts(pages, c)}


def _record(cur: psycopg.Cursor, snap: str, c: Classified, cvid: str, run: Run) -> dict:
    ids = {r.index: uuid5(f"bger|{r.docket}|{r.decision_date.isoformat()}") for r in c.loaded}
    cur.execute("SELECT count(*) FROM corpus.ruling_source_ref WHERE snapshot_id = %s AND source = %s", (snap, SOURCE))
    before_refs = cur.fetchone()[0]
    cur.executemany(
        """INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin)
           VALUES (%s, %s, %s, %s, false) ON CONFLICT DO NOTHING""",
        [(SOURCE, r.aza_id, ids[r.index], snap) for r in c.loaded],
    )
    cur.execute("SELECT count(*) FROM corpus.ruling_source_ref WHERE snapshot_id = %s AND source = %s", (snap, SOURCE))
    refs_written = cur.fetchone()[0] - before_refs
    # one observation per ruling and source (unique): the earliest page wins (rows are in date order)
    first: dict[str, PageRow] = {}
    for r in c.loaded:
        first.setdefault(ids[r.index], r)
    pub = [(rid, r.list_date, r.starred, r.area or None, snap) for rid, r in first.items()]
    cur.execute("SELECT count(*) FROM corpus.publication_observation WHERE source = 'neuheiten'")
    before_pub = cur.fetchone()[0]
    cur.executemany(
        """INSERT INTO corpus.publication_observation (ruling_id, source, quality, observed_date, star, sachgebiet,
           snapshot_id) VALUES (%s, 'neuheiten', 'exact', %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        pub,
    )
    cur.execute("SELECT count(*) FROM corpus.publication_observation WHERE source = 'neuheiten'")
    pub_written = cur.fetchone()[0] - before_pub
    subj = [(rid, r.area, r.starred, snap) for rid, r in first.items() if r.area.strip()]
    cur.execute("SELECT count(*) FROM corpus.subject_observation WHERE source = 'neuheiten'")
    before_subj = cur.fetchone()[0]
    cur.executemany(
        """INSERT INTO corpus.subject_observation (ruling_id, source, rubric, star, snapshot_id)
           VALUES (%s, 'neuheiten', %s, %s, %s) ON CONFLICT DO NOTHING""",
        subj,
    )
    cur.execute("SELECT count(*) FROM corpus.subject_observation WHERE source = 'neuheiten'")
    subj_written = cur.fetchone()[0] - before_subj
    cur.execute("SELECT count(*) FROM corpus.ingest_exclusion WHERE snapshot_id = %s", (snap,))
    before_exc = cur.fetchone()[0]
    cur.executemany(
        """INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date,
           reason_code, detail, component_version_id, run_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        [
            (snap, SOURCE, ext, r.case, r.decision_date, reason, json.dumps(detail), cvid, run.run_id)
            for r, ext, reason, detail in c.exclusions
        ],
    )
    cur.execute("SELECT count(*) FROM corpus.ingest_exclusion WHERE snapshot_id = %s", (snap,))
    exc_written = cur.fetchone()[0] - before_exc
    return {
        "written": refs_written,
        "already_loaded": len(c.loaded) - refs_written,
        "publication_observations_written": pub_written,
        "publication_observations_skipped": len(pub) - pub_written,
        "subject_observations_written": subj_written,
        "exclusions_written": exc_written,
    }


def _closure(cur: psycopg.Cursor, snap: str, c: Classified) -> dict:
    """Before commit: refs and exclusions of the snapshot are exactly what `classify` decided."""
    cur.execute(
        """SELECT row_count, loaded_refs, exclusions, unaccounted_rows, closure_ok, exclusions_by_reason
           FROM corpus.v_ingest_closure WHERE snapshot_id = %s""",
        (snap,),
    )
    found = cur.fetchone()
    if found is None:
        raise RuntimeError(f"ingest closure: snapshot {snap} has no source ref and no exclusion")
    row_count, refs, excluded, unaccounted, ok, by_reason = found
    if refs != len(c.loaded) or excluded != len(c.exclusions) or by_reason != c.by_reason():
        raise RuntimeError(
            f"ingest closure failed for snapshot {snap}: {refs} refs + {excluded} exclusions {by_reason}, this run "
            f"computed {len(c.loaded)} + {len(c.exclusions)} {c.by_reason()} (F-04)"
        )
    if unaccounted != len(c.not_in_base):
        raise RuntimeError(f"ingest closure: {unaccounted} rows unaccounted, {len(c.not_in_base)} not_in_base")
    return {"row_count": row_count, "source_refs": refs, "exclusions": excluded, "closure_ok": bool(ok)}


def load_neuheiten(conn: psycopg.Connection, directory: Path, actor: str, revision: str = HF_REVISION) -> dict:
    """Load the pages of `directory` in one transaction. Idempotent."""
    pages = read_pages(directory)
    with conn.cursor() as cur:
        pvid, cvid, cfg = _pinned_config(cur)
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="ingest",
        step="ingest",
        operation="ingest.neuheiten",
        component_version_id=cvid,
        params={"hf_repo": HF_REPO, "hf_revision": revision, "manifest_sha256": pages.manifest_sha256},
        code_paths=CODE_PATHS,
        actor=actor,
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ops.source_snapshot (source, revision, uri, file_sha256, byte_size, row_count,
                   retrieved_at) VALUES (%s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT ON CONSTRAINT source_snapshot_uq DO NOTHING""",
                (
                    SNAPSHOT_KIND,
                    revision,
                    f"hf://datasets/{HF_REPO}/{HF_FOLDER}/*.html@{revision}",
                    pages.manifest_sha256,
                    pages.byte_size,
                    len(pages.rows),
                ),
            )
            cur.execute(
                "SELECT snapshot_id::text, row_count FROM ops.source_snapshot WHERE source = %s AND revision = %s "
                "AND file_sha256 = %s",
                (SNAPSHOT_KIND, revision, pages.manifest_sha256),
            )
            snap, row_count = cur.fetchone()
            cur.execute("SELECT corpus.lock_source_rows(%s)", (snap,))
            if row_count != len(pages.rows):
                raise RuntimeError(f"snapshot {snap} records {row_count} rows, the pages hold {len(pages.rows)}")
            c = classify(pages.rows, _corpus_keys(cur), cfg)
            written = _record(cur, snap, c, cvid, run)
            closure = _closure(cur, snap, c)
            summary = {"snapshot_id": snap, **_counts(pages, c), **written, **closure}
            flat = {k: int(v) for k, v in summary.items() if isinstance(v, int)}  # closure_ok: bool -> 1/0
            flat |= {f"excluded_{k.lower()}": v for k, v in c.by_reason().items()}
            metrics(cur, run, "ingest", flat, unit="rows")
            level = "info" if closure["closure_ok"] else "warning"
            events(
                cur,
                run,
                "ingest",
                [
                    (
                        1,
                        level,
                        "ingest.neuheiten.loaded",
                        "Neuheiten pages read: every entry a source ref or an exclusion, not_in_base counted (F-04)",
                        {k: v for k, v in summary.items() if k != "snapshot_id"},
                        None,
                        None,
                    )
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {"run_id": run.run_id, **summary}


def main(argv: list[str] | None = None) -> int:
    from src.db.pg import connect

    ap = argparse.ArgumentParser(prog="python -m src.ingest.neuheiten", description=__doc__.splitlines()[0])
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder of YYYYMMDD.html pages")
    ap.add_argument("--revision", default=HF_REVISION, help="HF dataset revision the pages come from")
    ap.add_argument("--dry-run", action="store_true", help="classify and print the counts; write nothing")
    args = ap.parse_args(argv)
    with connect(args.database_url, actor="ingest-cli") as conn:
        if args.dry_run:
            out = dry_run(conn, args.dir)
        else:
            out = load_neuheiten(conn, args.dir, actor="ingest-cli", revision=args.revision)
    print(json.dumps(out, indent=2, default=str))
    return 0 if args.dry_run or out.get("closure_ok") else 1


if __name__ == "__main__":
    sys.exit(main())

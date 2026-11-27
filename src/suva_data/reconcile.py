"""Build the canonical `rulings` table from `source_records`, applying the hierarchy of truth.

docs/ARCHITECTURE.md sections 4, 6 and 6.1. In short:

* One ruling per (docket, decision_date).
* For every field, the value from the highest tier that has a VALID value wins. A lower tier never
  overrides a higher one. Every disagreement and every rejected value is written to `conflicts`.
* Records of the same source for the same ruling are collapsed: the first by source_key is the
  primary, the others are marked 'duplicate', and their fields fill gaps in the primary.
* The canonical text is the highest-tier text that passes the bad-text check.
* Nothing is deleted from `source_records` / `ruling_texts`; they only get a ruling and a status.

The whole step is derived state: it can be re-run at any time and gives the same result.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass, field

from . import config
from .models import DOCKET_RE, division_of

LANGUAGES = {"de", "fr", "it"}
# Order in which sources are consulted (tier first; within tier 1 the lists come before ruling pages).
SOURCE_ORDER = sorted(config.SOURCE_TIER, key=lambda s: (config.SOURCE_TIER[s], s))
TEXT_SOURCES = (config.ENTSCHEIDSUCHE, config.SWISS_CASELAW)
# Fields taken from sources. `division` is derived from the docket itself.
# Links differ by design between sources (search.bger.ch vs relevancy.bger.ch); that is not a disagreement.
NOT_COMPARED = frozenset({"official_url"})
RESOLVED_FIELDS = tuple(f for f in config.CANONICAL_FIELDS if f != "division")


@dataclass
class _Rec:
    id: int
    source: str
    source_key: str
    docket: str
    decision_date: str | None
    fields: dict
    text: tuple | None = None  # (sha256_normalized, bad_reason, char_count)


@dataclass
class ReconcileReport:
    source_records: int = 0
    rejected_at_load: int = 0
    skipped: int = 0
    used: int = 0
    duplicates: int = 0
    rulings: int = 0
    rulings_in_window: int = 0
    rulings_removed: int = 0
    canonical_texts: int = 0
    rulings_without_valid_text: int = 0
    conflicts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else str(value)[:10]


def _valid(fieldname: str, value, decision_date: str) -> bool:
    if value is None or value == "" or value == []:
        return False
    if fieldname == "language":
        return value in LANGUAGES
    if fieldname == "starred":
        return isinstance(value, bool)
    if fieldname == "publication_date":
        try:
            dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            return False
        return str(value)[:10] >= decision_date
    if fieldname == "cited_decisions":
        return isinstance(value, list)
    return isinstance(value, str) and bool(value.strip())


def _comparable(fieldname: str, value):
    """Form used to decide whether two sources really disagree (wording noise is not a conflict)."""
    if fieldname == "cited_decisions":
        return sorted(set(value))
    if fieldname == "publication_date":
        return str(value)[:10]
    if isinstance(value, str):
        return " ".join(value.split()).rstrip(" ,;.").casefold()
    return value


def _show(value) -> str | None:
    if value is None:
        return None
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 300 else s[:297] + "..."


def _merge_same_source(records: list[_Rec]) -> dict:
    """Combine the fields of one source's records for one ruling. Records are sorted by source_key."""
    merged: dict = {}
    for r in records:
        for k, v in r.fields.items():
            if v is None or v == "" or v == []:
                continue
            if k not in merged:
                merged[k] = v
            elif k == "publication_date":
                merged[k] = min(str(merged[k])[:10], str(v)[:10])  # first time it was published
            elif k == "starred":
                merged[k] = bool(merged[k]) or bool(v)
    return merged


def reconcile(conn, window: config.Window = config.DEFAULT_WINDOW, extra_dockets: frozenset[str] = frozenset()) -> ReconcileReport:
    rep = ReconcileReport()
    conflicts: list[tuple] = []  # (docket, decision_date, field, kind, winner_source, loser_source, winner_value, loser_value)

    with conn.transaction():
        cur = conn.cursor()
        cur.execute(
            """SELECT sr.id, sr.source, sr.source_key, sr.docket, sr.decision_date, sr.fields, sr.status,
                      t.sha256_normalized, t.bad_reason, t.char_count
               FROM source_records sr LEFT JOIN ruling_texts t ON t.source_record_id = sr.id
               ORDER BY sr.source, sr.source_key"""
        )
        groups: dict[tuple[str, str], dict[str, list[_Rec]]] = defaultdict(lambda: defaultdict(list))
        status_updates: dict[int, tuple[str, str | None]] = {}
        for rid, source, skey, docket, ddate, fields, status, sha, bad, chars in cur.fetchall():
            rep.source_records += 1
            if status == "rejected":
                rep.rejected_at_load += 1
                continue
            ddate = _iso(ddate)
            if not ddate or not DOCKET_RE.match(docket or ""):
                rep.skipped += 1
                status_updates[rid] = ("rejected", "reconcile: no decision date or invalid case number")
                conflicts.append((docket or "", ddate, "decision_date" if not ddate else "docket", "invalid_value", None, source, None, _show(ddate or docket)))
                continue
            if not (window.contains(ddate) or docket in extra_dockets):
                rep.skipped += 1
                status_updates[rid] = ("loaded", "reconcile: outside the window and not an extra case")
                continue
            groups[(docket, ddate)][source].append(
                _Rec(rid, source, skey, docket, ddate, fields or {}, (sha, bad, chars) if sha else None)
            )

        dates_by_docket: dict[str, list[str]] = defaultdict(list)
        for docket, ddate in groups:
            dates_by_docket[docket].append(ddate)

        ruling_rows: list[tuple] = []
        rec_to_ruling: list[tuple] = []  # (source_record_id, docket, decision_date)
        canonical_record_ids: list[int] = []

        for (docket, ddate) in sorted(groups, key=lambda k: (k[1], k[0])):
            by_source = groups[(docket, ddate)]
            flags: dict = {"sources": [s for s in SOURCE_ORDER if s in by_source]}
            merged: dict[str, dict] = {}
            primaries: dict[str, _Rec] = {}

            for source in SOURCE_ORDER:
                recs = by_source.get(source)
                if not recs:
                    continue
                recs.sort(key=lambda r: r.source_key)
                primaries[source] = recs[0]
                merged[source] = _merge_same_source(recs)
                status_updates[recs[0].id] = ("used", None)
                rep.used += 1
                for extra in recs[1:]:
                    rep.duplicates += 1
                    same_text = bool(extra.text and recs[0].text and extra.text[0] == recs[0].text[0])
                    status_updates[extra.id] = ("duplicate", f"reconcile: duplicate of {recs[0].source_key}")
                    conflicts.append((docket, ddate, "record", "duplicate_collapsed", source, source, recs[0].source_key,
                                      f"{extra.source_key} ({'same text' if same_text else 'no text' if not extra.text else 'DIFFERENT text'})"))
                    if extra.text and recs[0].text and not same_text:
                        flags["duplicate_with_different_text"] = True
                for r in recs:
                    rec_to_ruling.append((r.id, docket, ddate))

            # --- fields: highest tier with a valid value wins -------------------------------------
            values: dict = {}
            field_sources: dict = {"division": "docket"}
            for f in RESOLVED_FIELDS:
                winner_source = None
                for source in SOURCE_ORDER:
                    if source not in merged or f not in merged[source]:
                        continue
                    v = merged[source][f]
                    if (source, f) in config.NEVER_CANONICAL:
                        continue  # kept in source_records, never trusted (Phase 0)
                    if not _valid(f, v, ddate):
                        conflicts.append((docket, ddate, f, "invalid_value", None, source, None, _show(v)))
                        continue
                    if winner_source is None:
                        winner_source, values[f] = source, v
                        field_sources[f] = source
                    elif f not in NOT_COMPARED and _comparable(f, v) != _comparable(f, values[f]):
                        conflicts.append((docket, ddate, f, "value_mismatch", winner_source, source, _show(values[f]), _show(v)))

            # --- text: highest tier that passes the bad-text check --------------------------------
            canonical = None
            good_hashes: dict[str, tuple] = {}
            for source in SOURCE_ORDER:
                p = primaries.get(source)
                if not p or not p.text:
                    continue
                sha, bad, chars = p.text
                if bad:
                    conflicts.append((docket, ddate, "text", "bad_text", None, source, None, f"{bad} ({chars} chars)"))
                    continue
                good_hashes[source] = (sha, chars)
                if canonical is None:
                    canonical = (source, p, sha, chars)
            if canonical:
                canonical_record_ids.append(canonical[1].id)
                field_sources["text"] = canonical[0]
                for source, (sha, chars) in good_hashes.items():
                    if source != canonical[0] and sha != canonical[2]:
                        flags["text_mismatch"] = True
                        conflicts.append((docket, ddate, "text", "text_mismatch", canonical[0], source,
                                          f"{canonical[2][:12]} ({canonical[3]} chars)", f"{sha[:12]} ({chars} chars)"))
                flags["text_sources"] = len(good_hashes)
            else:
                flags["no_valid_text"] = True
                rep.rulings_without_valid_text += 1

            for source in TEXT_SOURCES:
                if source not in by_source:
                    conflicts.append((docket, ddate, "record", "missing_in_source", None, source, None, None))
            if config.BGER_LIST not in by_source:
                flags["not_on_crawled_list"] = True  # publication date / star not known from tier 1

            in_window = window.contains(ddate)
            rep.rulings += 1
            rep.rulings_in_window += in_window
            ruling_rows.append((
                docket, ddate, division_of(docket), values.get("language"), values.get("publication_date"),
                values.get("starred"), values.get("area"), values.get("subject"), values.get("outcome"),
                json.dumps(values["cited_decisions"], ensure_ascii=False) if "cited_decisions" in values else None,
                values.get("official_url"), json.dumps(field_sources, sort_keys=True),
                json.dumps(flags, sort_keys=True), in_window,
            ))

        # A case number with several decision dates is suspicious unless every source agrees on each date.
        for docket, dates in dates_by_docket.items():
            if len(dates) > 1:
                source_sets = [frozenset(groups[(docket, d)]) & frozenset(TEXT_SOURCES) for d in dates]
                if len(set(source_sets)) > 1 or any(len(s) < 2 for s in source_sets):
                    for d in sorted(dates):
                        conflicts.append((docket, d, "decision_date", "value_mismatch", None, None,
                                          ", ".join(sorted(dates)), "sources disagree on the decision date of this case number"))

        # ---------------------------------------------------------------- write
        cur.execute(
            """CREATE TEMP TABLE _r (docket text, decision_date date, division text, language text, publication_date date,
                   starred boolean, area text, subject text, outcome text, cited_decisions jsonb, official_url text,
                   field_sources jsonb, flags jsonb, in_window boolean, ord serial) ON COMMIT DROP"""
        )
        with cur.copy(
            "COPY _r (docket, decision_date, division, language, publication_date, starred, area, subject, outcome,"
            " cited_decisions, official_url, field_sources, flags, in_window) FROM STDIN"
        ) as cp:
            for row in ruling_rows:
                cp.write_row(row)
        cur.execute(
            """INSERT INTO rulings (docket, decision_date, division, language, publication_date, starred, area, subject,
                                    outcome, cited_decisions, official_url, field_sources, flags, in_window)
               SELECT docket, decision_date, division, language, publication_date, starred, area, subject, outcome,
                      cited_decisions, official_url, field_sources, flags, in_window
               FROM _r ORDER BY ord
               ON CONFLICT (docket, decision_date) DO UPDATE SET
                   division = EXCLUDED.division, language = EXCLUDED.language, publication_date = EXCLUDED.publication_date,
                   starred = EXCLUDED.starred, area = EXCLUDED.area, subject = EXCLUDED.subject, outcome = EXCLUDED.outcome,
                   cited_decisions = EXCLUDED.cited_decisions, official_url = EXCLUDED.official_url,
                   field_sources = EXCLUDED.field_sources, flags = EXCLUDED.flags, in_window = EXCLUDED.in_window"""
        )
        # Rulings no longer supported by any source record: remove, unless something is attached to them.
        cur.execute(
            """SELECT r.id, r.docket,
                      EXISTS (SELECT 1 FROM labels l WHERE l.ruling_id = r.id) OR
                      EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id)
               FROM rulings r WHERE NOT EXISTS (SELECT 1 FROM _r WHERE _r.docket = r.docket AND _r.decision_date = r.decision_date)"""
        )
        stale = cur.fetchall()
        attached = [d for _, d, has in stale if has]
        if attached:
            raise RuntimeError(f"rulings with labels or gold summaries lost all their source records: {sorted(attached)}")
        if stale:
            cur.execute("DELETE FROM rulings WHERE id = ANY(%s)", ([i for i, _, _ in stale],))
            rep.rulings_removed = len(stale)

        cur.execute("CREATE TEMP TABLE _s (id bigint PRIMARY KEY, docket text, decision_date date, status text, reason text) ON COMMIT DROP")
        ruling_of = {rid: (d, dd) for rid, d, dd in rec_to_ruling}
        with cur.copy("COPY _s (id, docket, decision_date, status, reason) FROM STDIN") as cp:
            for rid in sorted(status_updates):
                status, reason = status_updates[rid]
                d, dd = ruling_of.get(rid, (None, None))
                cp.write_row((rid, d, dd, status, reason))
        cur.execute(
            """UPDATE source_records sr SET status = s.status, status_reason = s.reason, ruling_id = r.id
               FROM _s s LEFT JOIN rulings r ON r.docket = s.docket AND r.decision_date = s.decision_date
               WHERE sr.id = s.id
                 AND (sr.status, sr.status_reason, sr.ruling_id) IS DISTINCT FROM (s.status, s.reason, r.id)"""
        )
        cur.execute("UPDATE ruling_texts SET is_canonical = false WHERE is_canonical AND NOT (source_record_id = ANY(%s))", (canonical_record_ids,))
        cur.execute(
            """UPDATE ruling_texts t SET ruling_id = sr.ruling_id FROM source_records sr
               WHERE t.source_record_id = sr.id AND t.ruling_id IS DISTINCT FROM sr.ruling_id"""
        )
        cur.execute("UPDATE ruling_texts SET is_canonical = true WHERE source_record_id = ANY(%s) AND NOT is_canonical", (canonical_record_ids,))
        rep.canonical_texts = len(canonical_record_ids)

        # conflicts are derived: rebuild, in a stable order
        cur.execute("TRUNCATE conflicts RESTART IDENTITY")
        conflicts.sort(key=lambda c: tuple("" if x is None else str(x) for x in c))
        cur.execute(
            """CREATE TEMP TABLE _c (docket text, decision_date date, field text, kind text, winner_source text,
                   loser_source text, winner_value text, loser_value text, ord serial) ON COMMIT DROP"""
        )
        with cur.copy("COPY _c (docket, decision_date, field, kind, winner_source, loser_source, winner_value, loser_value) FROM STDIN") as cp:
            for c in conflicts:
                cp.write_row(c)
        cur.execute(
            """INSERT INTO conflicts (ruling_id, docket, decision_date, field, kind, winner_source, loser_source, winner_value, loser_value)
               SELECT r.id, c.docket, c.decision_date, c.field, c.kind, c.winner_source, c.loser_source, c.winner_value, c.loser_value
               FROM _c c LEFT JOIN rulings r ON r.docket = c.docket AND r.decision_date = c.decision_date ORDER BY c.ord"""
        )
        counts: dict = defaultdict(int)
        for c in conflicts:
            counts[f"{c[3]}:{c[2]}"] += 1
        rep.conflicts = dict(sorted(counts.items()))
    return rep


def load_statute_refs(conn, rows) -> int:
    """rows: dicts with decision_id, law_code, article, paragraph, mention_count (Swiss Case Law, derived)."""
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _st (decision_id text, law_code text, article text, paragraph text, mention_count integer) ON COMMIT DROP")
        with cur.copy("COPY _st FROM STDIN") as cp:
            for r in rows:
                if r.get("law_code") and r.get("article"):
                    cp.write_row((r["decision_id"], r["law_code"], r["article"], r.get("paragraph") or "", r.get("mention_count")))
        cur.execute("TRUNCATE statute_refs")
        cur.execute(
            """INSERT INTO statute_refs (ruling_id, law_code, article, paragraph, mention_count)
               SELECT sr.ruling_id, s.law_code, s.article, s.paragraph, sum(s.mention_count)
               FROM _st s JOIN source_records sr ON sr.source = %s AND sr.source_key = s.decision_id
               WHERE sr.ruling_id IS NOT NULL
               GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""",
            (config.SWISS_CASELAW,),
        )
        return cur.rowcount

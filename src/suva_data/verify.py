"""Checks that the built database is what it should be, a content fingerprint, and the quality report.

docs/DATA_LAYER.md section 6 ("Invariants"), 6.1 (#4 accounting, #10 report) and 7 (reproducibility).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config

# Tables and the columns that define the dataset's content. Surrogate ids and timestamps are left out
# on purpose: two builds from the same snapshot must give the same fingerprint.
_FINGERPRINT_SQL = {
    "rulings": """SELECT md5(coalesce(string_agg(md5(ROW(docket, decision_date, division, language, publication_date, starred, area,
                         subject, outcome, cited_decisions, official_url, field_sources, flags, in_window)::text), '' ORDER BY decision_date, docket), ''))
                  FROM rulings""",
    "source_records": """SELECT md5(coalesce(string_agg(md5(ROW(sr.source, sr.source_key, sr.docket, sr.decision_date, sr.fields, sr.record,
                                sr.status, sr.status_reason, r.docket, r.decision_date)::text), '' ORDER BY sr.source, sr.source_key), ''))
                         FROM source_records sr LEFT JOIN rulings r ON r.id = sr.ruling_id""",
    "ruling_texts": """SELECT md5(coalesce(string_agg(md5(ROW(sr.source, sr.source_key, md5(t.text), t.sha256_normalized, t.char_count,
                              t.bad_reason, t.is_canonical)::text), '' ORDER BY sr.source, sr.source_key), ''))
                       FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id""",
    "conflicts": """SELECT md5(coalesce(string_agg(md5(ROW(docket, decision_date, field, kind, winner_source, loser_source, winner_value,
                           loser_value)::text), '' ORDER BY id), '')) FROM conflicts""",
    "statute_refs": """SELECT md5(coalesce(string_agg(md5(ROW(r.docket, r.decision_date, s.law_code, s.article, s.paragraph, s.mention_count)::text), ''
                              ORDER BY r.decision_date, r.docket, s.law_code, s.article, s.paragraph), ''))
                       FROM statute_refs s JOIN rulings r ON r.id = s.ruling_id""",
    "labels": """SELECT md5(coalesce(string_agg(md5(ROW(r.docket, r.decision_date, l.label_set, l.value, l.quarter, l.metadata, l.created_by)::text), ''
                        ORDER BY r.decision_date, r.docket, l.label_set), ''))
                 FROM labels l JOIN rulings r ON r.id = l.ruling_id""",
    "gold_summaries": """SELECT md5(coalesce(string_agg(md5(ROW(r.docket, r.decision_date, g.language, g.title, g.body, g.author, g.source_url,
                                g.source_file, g.version, g.is_current)::text), '' ORDER BY r.decision_date, r.docket, g.language, g.version), ''))
                         FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id""",
}


def fingerprint(conn) -> dict:
    cur = conn.cursor()
    tables = {}
    for name, sql in _FINGERPRINT_SQL.items():
        cur.execute(sql)
        tables[name] = cur.fetchone()[0]
    combined = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    return {"dataset": combined, "tables": tables}


def _one(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchone()[0]


def check_invariants(
    conn, expected_gold: int, expected_labels: int, window: config.Window = config.DEFAULT_WINDOW
) -> list[tuple[str, bool, str]]:
    """Returns (name, passed, detail) for every invariant."""
    cur = conn.cursor()
    out: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        out.append((name, bool(ok), str(detail)))

    n = _one(cur, "SELECT count(*) FROM labels WHERE label_set = %s AND value = 'relevant'", (config.LABEL_SET_XLSX,))
    check("relevance labels loaded", n == expected_labels, f"{n} of {expected_labels}")
    n = _one(cur, "SELECT count(*) FROM labels l JOIN rulings r ON r.id = l.ruling_id WHERE r.docket = '8C_458/2025'")
    # Only meaningful once Suva's xlsx has been loaded.
    check("malformed xlsx row mapped to 8C_458/2025", n == 1 or expected_labels == 0, n)
    n = _one(cur, "SELECT count(*) FROM labels WHERE metadata->>'xlsx_title' ILIKE '%%Kantonsgericht%%'")
    check("cantonal xlsx row not loaded", n == 0, n)
    n = _one(
        cur,
        """SELECT count(*) FROM labels l JOIN rulings r ON r.id = l.ruling_id
                     WHERE l.quarter IS DISTINCT FROM to_char(r.decision_date, 'YYYY "Q"Q')""",
    )
    check("label quarter equals decision-date quarter", n == 0, f"{n} mismatches")

    n_r = _one(cur, "SELECT count(DISTINCT ruling_id) FROM gold_summaries WHERE is_current")
    n_s = _one(cur, "SELECT count(*) FROM gold_summaries WHERE is_current")
    check(
        "gold summaries loaded (DE + FR each)",
        n_r == expected_gold and n_s == 2 * expected_gold,
        f"{n_r} rulings, {n_s} summaries",
    )

    n = _one(
        cur,
        """SELECT count(*) FROM rulings r
                     WHERE (EXISTS (SELECT 1 FROM labels l WHERE l.ruling_id = r.id) OR EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id))
                       AND NOT EXISTS (SELECT 1 FROM ruling_texts t WHERE t.ruling_id = r.id AND t.is_canonical)""",
    )
    check("every labelled / gold-summary ruling has a canonical text", n == 0, f"{n} without")
    n = _one(
        cur,
        "SELECT count(*) FROM rulings r WHERE in_window AND NOT EXISTS (SELECT 1 FROM ruling_texts t WHERE t.ruling_id = r.id AND t.is_canonical)",
    )
    n_flag = _one(cur, "SELECT count(*) FROM rulings WHERE in_window AND flags ? 'no_valid_text'")
    check("every ruling without a canonical text is flagged", n == n_flag, f"{n} without text, {n_flag} flagged")
    n = _one(
        cur,
        "SELECT count(*) FROM (SELECT ruling_id FROM ruling_texts WHERE is_canonical GROUP BY 1 HAVING count(*) > 1) x",
    )
    check("at most one canonical text per ruling", n == 0, n)
    n = _one(cur, "SELECT count(*) FROM ruling_texts WHERE is_canonical AND bad_reason IS NOT NULL")
    check("no bad text is canonical", n == 0, n)

    n = _one(
        cur,
        "SELECT count(*) FROM rulings WHERE in_window IS DISTINCT FROM (decision_date BETWEEN %s AND %s)",
        (window.decision_from, window.decision_to),
    )
    check("in_window matches the decision-date window", n == 0, n)
    n = _one(
        cur,
        """SELECT count(*) FROM rulings r WHERE NOT in_window
                     AND NOT EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id) AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.ruling_id = r.id)""",
    )
    check("rulings outside the window are only gold-summary / labelled cases", n == 0, n)

    # accounting: every source record is used, a duplicate, rejected, or deliberately left out
    cur.execute("SELECT status, (ruling_id IS NOT NULL), count(*) FROM source_records GROUP BY 1, 2")
    rows = cur.fetchall()
    bad = sum(c for status, has, c in rows if (status in ("used", "duplicate")) != has)
    unexplained = _one(cur, "SELECT count(*) FROM source_records WHERE status = 'loaded' AND status_reason IS NULL")
    check(
        "every source record is accounted for",
        bad == 0 and unexplained == 0,
        f"{bad} inconsistent, {unexplained} unexplained",
    )
    n = _one(
        cur,
        "SELECT count(*) FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id WHERE t.ruling_id IS DISTINCT FROM sr.ruling_id",
    )
    check("texts point at the same ruling as their record", n == 0, n)

    # hierarchy of truth
    n = _one(
        cur,
        """SELECT count(*) FROM rulings r JOIN ruling_texts c ON c.ruling_id = r.id AND c.is_canonical
                     JOIN source_records cs ON cs.id = c.source_record_id
                     JOIN source_records hs ON hs.ruling_id = r.id AND hs.status = 'used' AND hs.source = %s
                     JOIN ruling_texts ht ON ht.source_record_id = hs.id AND ht.bad_reason IS NULL
                     WHERE cs.source = %s""",
        (config.ENTSCHEIDSUCHE, config.SWISS_CASELAW),
    )
    check("tier 3 text is never canonical when a valid tier 2 text exists", n == 0, n)
    n = _one(
        cur,
        "SELECT count(*) FROM rulings WHERE starred IS NOT NULL AND field_sources->>'starred' <> %s",
        (config.BGER_LIST,),
    )
    check("the publication star only ever comes from bger.ch lists", n == 0, n)
    return out


def verify_manifest_files(manifest: dict, snapshot_dir: Path = config.SNAPSHOT_DIR) -> list[str]:
    """Compare snapshot files on disk with the manifest. Returns human-readable differences."""
    problems = []
    for rel, meta in sorted(manifest.get("files", {}).items()):
        p = snapshot_dir / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
            continue
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != meta["sha256"]:
            problems.append(f"changed: {rel}")
    on_disk = {
        str(p.relative_to(snapshot_dir).as_posix())
        for p in snapshot_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }
    for rel in sorted(on_disk - set(manifest.get("files", {}))):
        problems.append(f"not in manifest: {rel}")
    return problems


def quality_report(
    conn,
    invariants,
    fp: dict,
    load_counts: dict,
    reconcile_report: dict,
    list_coverage: dict | None,
    labels_dropped: list,
) -> str:
    cur = conn.cursor()

    def table(sql, headers, params=None):
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        lines += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
        return "\n".join(lines) if rows else "_none_"

    passed = sum(1 for _, ok, _ in invariants if ok)
    L = [
        "# Data quality report",
        "",
        "Generated by `suva_data build`. Do not edit by hand.",
        "",
        f"- Dataset fingerprint: `{fp['dataset']}`",
        f"- Decision-date window: {config.DEFAULT_WINDOW.decision_from} to {config.DEFAULT_WINDOW.decision_to}",
        f"- Swiss Case Law revision: `{config.SWISS_CASELAW_REVISION}`",
        f"- Checks passed: {passed} of {len(invariants)}",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    L += [f"| {name} | {'PASS' if ok else '**FAIL**'} | {detail} |" for name, ok, detail in invariants]

    L += [
        "",
        "## Rulings",
        "",
        table(
            """SELECT to_char(decision_date, 'YYYY "Q"Q'), count(*), count(*) FILTER (WHERE in_window),
                          count(*) FILTER (WHERE division IN ('8C','9C')), count(*) FILTER (WHERE starred),
                          count(*) FILTER (WHERE starred IS NULL), count(*) FILTER (WHERE publication_date IS NULL)
                   FROM rulings GROUP BY 1 ORDER BY 1""",
            [
                "Decision quarter",
                "Rulings",
                "In window",
                "8C/9C",
                "Starred",
                "Star not known",
                "Publication date not known",
            ],
        ),
        "",
        "## Relevance (view `v_relevance`)",
        "",
        table(
            "SELECT decision_quarter, relevance, basis, count(*) FROM v_relevance GROUP BY 1,2,3 ORDER BY 1,2,3",
            ["Decision quarter", "Relevance", "Basis", "Rulings"],
        ),
        "",
        "## Source records: every row accounted for",
        "",
        table(
            "SELECT source, status, count(*) FROM source_records GROUP BY 1,2 ORDER BY 1,2",
            ["Source", "Status", "Records"],
        ),
        "",
        "Load step counts (read = inserted + updated + unchanged + rejected):",
        "",
        "```json",
        json.dumps(load_counts, indent=2, sort_keys=True),
        "```",
        "",
        "## Where each canonical value comes from",
        "",
        table(
            """SELECT k, v, count(*) FROM rulings, jsonb_each_text(field_sources) AS e(k, v) GROUP BY 1,2 ORDER BY 1,2""",
            ["Field", "Source", "Rulings"],
        ),
        "",
        "## Full texts",
        "",
        table(
            """SELECT sr.source, count(*), count(*) FILTER (WHERE t.bad_reason IS NOT NULL), count(*) FILTER (WHERE t.is_canonical),
                          round(sum(t.char_count) / 1e6, 1)
                   FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id GROUP BY 1 ORDER BY 1""",
            ["Source", "Texts", "Bad", "Canonical", "Million chars"],
        ),
        "",
        "Rulings by number of valid, independent text sources:",
        "",
        table(
            "SELECT coalesce(flags->>'text_sources', '0'), count(*) FROM rulings GROUP BY 1 ORDER BY 1",
            ["Valid text sources", "Rulings"],
        ),
        "",
        "Bad texts (stored, flagged, never canonical):",
        "",
        table(
            """SELECT sr.docket, sr.decision_date, sr.source, t.bad_reason, t.char_count,
                          EXISTS (SELECT 1 FROM ruling_texts c WHERE c.ruling_id = t.ruling_id AND c.is_canonical)
                   FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id WHERE t.bad_reason IS NOT NULL ORDER BY 1,2,3""",
            ["Case", "Decided", "Source", "Reason", "Chars", "Fixed by another source"],
        ),
        "",
        "## Conflicts between sources",
        "",
        table(
            "SELECT kind, field, coalesce(winner_source,''), coalesce(loser_source,''), count(*) FROM conflicts GROUP BY 1,2,3,4 ORDER BY 1,2,3,4",
            ["Kind", "Field", "Winner", "Loser", "Count"],
        ),
        "",
        "## Known gaps",
        "",
    ]
    if list_coverage:
        L.append(
            f"- bger.ch lists present: {list_coverage.get('first_list_date')} to {list_coverage.get('last_list_date')} "
            f"({list_coverage.get('lists')} lists). Weekdays without a list for the window plus look-ahead: "
            f"**{len(list_coverage.get('window_missing_weekdays', []))}**. Rulings published on those days have no star and no tier-1 publication date."
        )
    for row, title, reason in labels_dropped:
        L.append(f"- xlsx row {row} dropped ({reason}): {title}")
    L += ["", "## Reconcile summary", "", "```json", json.dumps(reconcile_report, indent=2, sort_keys=True), "```", ""]
    return "\n".join(L)

"""The hierarchy of truth, duplicate handling and bad-text fallback (docs/DATA_LAYER.md 4, 6, 6.1)."""

import pytest

from suva_data import config, load, reconcile as rec, verify
from suva_data.models import SourceRecord

pytestmark = pytest.mark.db

GOOD = "Urteil vom 11. Dezember 2025. " + "Erwägung. " * 100 + "Im Namen des Schweizerischen Bundesgerichts. Die Präsidentin: X. Der Gerichtsschreiber: Y."
GOOD_SPACED = GOOD.replace(" ", " \n ")  # same text, different whitespace: must NOT count as a mismatch
OTHER = GOOD.replace("Erwägung", "Erwaegung")  # a real difference
ERROR_PAGE = "Dokument nicht gefunden. Dieser AZA-Entscheid ist in elektronischer Form nicht verfügbar."


def R(source, key, docket="8C_72/2025", date="2025-12-11", text=None, **fields):
    return SourceRecord(source=source, source_key=key, docket=docket, decision_date=date, fields=fields, record={}, text=text)


def build(conn, records, extras=frozenset()):
    load.load_source_records(conn, records)
    return rec.reconcile(conn, config.DEFAULT_WINDOW, extras)


def ruling(conn, docket="8C_72/2025", date="2025-12-11"):
    cur = conn.execute(
        "SELECT language, publication_date::text, starred, area, subject, outcome, field_sources, flags, in_window, id FROM rulings WHERE docket=%s AND decision_date=%s",
        (docket, date))
    row = cur.fetchone()
    return dict(zip(["language", "publication_date", "starred", "area", "subject", "outcome", "field_sources", "flags", "in_window", "id"], row)) if row else None


def canonical_source(conn, ruling_id):
    row = conn.execute("SELECT source FROM ruling_texts WHERE ruling_id=%s AND is_canonical", (ruling_id,)).fetchone()
    return row[0] if row else None


def conflicts(conn, kind=None):
    q = "SELECT kind, field, winner_source, loser_source FROM conflicts" + (" WHERE kind=%s" if kind else "") + " ORDER BY id"
    return conn.execute(q, (kind,) if kind else ()).fetchall()


def test_higher_tier_wins_each_field_and_sources_are_recorded(db_conn):
    build(db_conn, [
        R(config.BGER_LIST, "2026-01-14:8C_72/2025", publication_date="2026-01-14", starred=False, area="Assurance-accidents", subject="rente d'invalidité"),
        R(config.ENTSCHEIDSUCHE, "CH_BGer_008_8C-72-2025_2025-12-11", text=GOOD, language="fr"),
        R(config.SWISS_CASELAW, "bger_8C_72_2025", text=GOOD, language="de", area="Unfallversicherung", subject="rente d'invalidité,", outcome="dismissed",
          publication_date="2026-01-20", starred=True),
    ])
    r = ruling(db_conn)
    assert r["language"] == "fr" and r["field_sources"]["language"] == config.ENTSCHEIDSUCHE  # tier 2 beats tier 3
    assert r["area"] == "Assurance-accidents" and r["field_sources"]["area"] == config.BGER_LIST  # tier 1 beats tier 3
    assert r["publication_date"] == "2026-01-14" and r["starred"] is False
    assert r["outcome"] == "dismissed" and r["field_sources"]["outcome"] == config.SWISS_CASELAW  # only tier 3 has it
    assert canonical_source(db_conn, r["id"]) == config.ENTSCHEIDSUCHE
    kinds = {(k, f) for k, f, _, _ in conflicts(db_conn)}
    assert ("value_mismatch", "language") in kinds and ("value_mismatch", "area") in kinds and ("value_mismatch", "publication_date") in kinds
    assert ("value_mismatch", "subject") not in kinds  # a trailing comma is not a disagreement
    assert ("text_mismatch", "text") not in kinds


def test_star_and_publication_date_unknown_when_not_on_a_list(db_conn):
    build(db_conn, [R(config.SWISS_CASELAW, "bger_8C_72_2025", text=GOOD, language="fr", starred=True, publication_date="2026-01-20")])
    r = ruling(db_conn)
    assert r["starred"] is None  # the dataset's star is never trusted; unknown is NULL, not false
    assert r["publication_date"] == "2026-01-20" and r["field_sources"]["publication_date"] == config.SWISS_CASELAW
    assert r["flags"]["not_on_crawled_list"] is True


def test_bad_text_in_higher_tier_falls_back_and_is_logged(db_conn):
    build(db_conn, [
        R(config.ENTSCHEIDSUCHE, "CH_BGer_008_8C-72-2025_2025-12-11", text=ERROR_PAGE, language="fr"),
        R(config.SWISS_CASELAW, "bger_8C_72_2025", text=GOOD, language="fr"),
    ])
    r = ruling(db_conn)
    assert canonical_source(db_conn, r["id"]) == config.SWISS_CASELAW
    assert conflicts(db_conn, "bad_text") == [("bad_text", "text", None, config.ENTSCHEIDSUCHE)]
    assert db_conn.execute("SELECT count(*) FROM ruling_texts").fetchone()[0] == 2  # the bad text is kept, not deleted


def test_no_valid_text_is_flagged(db_conn):
    rep = build(db_conn, [R(config.SWISS_CASELAW, "bger_8C_72_2025", text=ERROR_PAGE, language="fr")])
    r = ruling(db_conn)
    assert rep.rulings_without_valid_text == 1 and r["flags"]["no_valid_text"] is True and canonical_source(db_conn, r["id"]) is None


def test_whitespace_differences_are_not_a_text_mismatch_but_real_ones_are(db_conn):
    build(db_conn, [
        R(config.ENTSCHEIDSUCHE, "es1", text=GOOD_SPACED), R(config.SWISS_CASELAW, "hf1", text=GOOD),
        R(config.ENTSCHEIDSUCHE, "es2", docket="8C_73/2025", text=GOOD), R(config.SWISS_CASELAW, "hf2", docket="8C_73/2025", text=OTHER),
    ])
    assert conflicts(db_conn, "text_mismatch") == [("text_mismatch", "text", config.ENTSCHEIDSUCHE, config.SWISS_CASELAW)]
    assert "text_mismatch" not in ruling(db_conn)["flags"] and ruling(db_conn, "8C_73/2025")["flags"]["text_mismatch"] is True


def test_exact_duplicates_collapse_and_fill_gaps(db_conn):
    rep = build(db_conn, [
        R(config.SWISS_CASELAW, "bger_8C_72_2025", text=GOOD, language="fr", publication_date="2026-01-14"),
        R(config.SWISS_CASELAW, "bger_8C_72_2025-D20251211", text=GOOD, language="fr", outcome="dismissed"),
    ])
    assert rep.rulings == 1 and rep.duplicates == 1
    r = ruling(db_conn)
    assert r["publication_date"] == "2026-01-14" and r["outcome"] == "dismissed"  # merged, not "keep one row"
    statuses = dict(db_conn.execute("SELECT source_key, status FROM source_records").fetchall())
    assert statuses == {"bger_8C_72_2025": "used", "bger_8C_72_2025-D20251211": "duplicate"}
    assert len(conflicts(db_conn, "duplicate_collapsed")) == 1


def test_same_case_number_on_two_dates_is_two_rulings(db_conn):
    recs = []
    for date in ("2026-01-26", "2026-03-18"):
        recs += [R(config.ENTSCHEIDSUCHE, f"es-{date}", docket="7B_1356/2025", date=date, text=GOOD + date),
                 R(config.SWISS_CASELAW, f"hf-{date}", docket="7B_1356/2025", date=date, text=GOOD + date)]
    rep = build(db_conn, recs)
    assert rep.rulings == 2 and rep.duplicates == 0
    assert not [c for c in conflicts(db_conn) if c[1] == "decision_date"]  # both sources agree on both dates


def test_sources_disagreeing_on_the_date_is_reported(db_conn):
    build(db_conn, [R(config.ENTSCHEIDSUCHE, "es", date="2025-12-11", text=GOOD), R(config.SWISS_CASELAW, "hf", date="2025-12-12", text=GOOD)])
    assert len([c for c in conflicts(db_conn, "value_mismatch") if c[1] == "decision_date"]) == 2


def test_ruling_listed_twice_takes_first_publication_and_any_star(db_conn):
    build(db_conn, [
        R(config.BGER_LIST, "2026-01-20:8C_72/2025", publication_date="2026-01-20", starred=True),
        R(config.BGER_LIST, "2026-01-14:8C_72/2025", publication_date="2026-01-14", starred=False),
        R(config.SWISS_CASELAW, "hf", text=GOOD),
    ])
    r = ruling(db_conn)
    assert r["publication_date"] == "2026-01-14" and r["starred"] is True


def test_window_and_extras(db_conn):
    recs = [R(config.SWISS_CASELAW, "in", text=GOOD),
            R(config.SWISS_CASELAW, "extra", docket="8C_178/2025", date="2025-07-09", text=GOOD),
            R(config.SWISS_CASELAW, "out", docket="8C_1/2025", date="2025-07-09", text=GOOD)]
    rep = build(db_conn, recs, extras=frozenset({"8C_178/2025"}))
    assert rep.rulings == 2 and rep.rulings_in_window == 1 and rep.skipped == 1
    assert ruling(db_conn, "8C_178/2025", "2025-07-09")["in_window"] is False
    assert ruling(db_conn, "8C_1/2025", "2025-07-09") is None
    assert db_conn.execute("SELECT status, status_reason FROM source_records WHERE source_key='out'").fetchone()[1].startswith("reconcile: outside")


def test_invalid_values_are_skipped_and_logged(db_conn):
    build(db_conn, [
        R(config.BGER_LIST, "l", publication_date="2025-12-01", starred=False),  # published before it was decided
        R(config.ENTSCHEIDSUCHE, "es", text=GOOD, language="xx"),
        R(config.SWISS_CASELAW, "hf", text=GOOD, language="fr", publication_date="2026-01-14"),
    ])
    r = ruling(db_conn)
    assert r["language"] == "fr" and r["publication_date"] == "2026-01-14"
    assert {(k, f, l) for k, f, _, l in conflicts(db_conn, "invalid_value")} == {
        ("invalid_value", "publication_date", config.BGER_LIST), ("invalid_value", "language", config.ENTSCHEIDSUCHE)}


def test_reconcile_is_idempotent_and_upgrades_when_a_higher_tier_arrives(db_conn):
    build(db_conn, [R(config.SWISS_CASELAW, "hf", text=GOOD, language="fr")])
    fp1 = verify.fingerprint(db_conn)["dataset"]
    rid = ruling(db_conn)["id"]
    rec.reconcile(db_conn)
    assert verify.fingerprint(db_conn)["dataset"] == fp1 and ruling(db_conn)["id"] == rid
    build(db_conn, [R(config.ENTSCHEIDSUCHE, "es", text=GOOD, language="fr"),
                    R(config.BGER_LIST, "2026-01-14:8C_72/2025", publication_date="2026-01-14", starred=True)])
    r = ruling(db_conn)
    assert r["id"] == rid  # same ruling row: labels and summaries attached to it survive
    assert canonical_source(db_conn, rid) == config.ENTSCHEIDSUCHE and r["starred"] is True


def test_invariants_pass_on_a_small_consistent_database(db_conn):
    build(db_conn, [R(config.ENTSCHEIDSUCHE, "es", text=GOOD, language="fr"), R(config.SWISS_CASELAW, "hf", text=GOOD, language="fr")])
    failed = [(n, d) for n, ok, d in verify.check_invariants(db_conn, expected_gold=0, expected_labels=0) if not ok]
    assert failed == []

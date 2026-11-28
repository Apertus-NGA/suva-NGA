"""Live ingest by publication date: add-only, ground truth first (src/suva_data/ingest.py).

Mocks declared (AGENTS.md G9): `FakeDownloads` (from test_hf_daily) stands in for downloading a Hugging Face
daily file, `FakeBger` for the bger.ch list adapter (its fetch never touches the network; its entries are
given by the test), and `FakeES` (from test_entscheidsuche) for the mirror's search endpoint. The database is
the real test database.
"""

from datetime import date

import pytest
from psycopg.types.json import Jsonb

from suva_data import config, ingest, load
from suva_data import reconcile as rec
from suva_data.models import SourceRecord
from suva_data.sources.bger_lists import FetchResult
from suva_data.sources.entscheidsuche import EntscheidsucheAdapter
from suva_data.sources.hf_daily import DailyFilesAdapter
from tests.test_entscheidsuche import FakeES
from tests.test_hf_daily import FakeDownloads, old_row, parquet_bytes
from tests.test_reconcile import GOOD, R, build, ruling

pytestmark = pytest.mark.db

JULY = ("2026-07-20", "2026-07-21")
OTHER_TEXT = GOOD.replace("Erwägung", "Erwaegung")


class FakeBger:
    """bger.ch list adapter that is blocked by default, or returns the given list entries."""

    def __init__(self, tmp_path, status="blocked", entries=()):
        self.snapshot_dir = tmp_path / "live" / config.BGER_LIST
        self.status, self.entries, self.fetch_calls = status, list(entries), 0

    def fetch(self, window):
        self.fetch_calls += 1
        blocked = self.status == "blocked"
        self.last_fetch = FetchResult(
            status=self.status,
            requested=1,
            blocked_on=window.decision_from if blocked else None,
            remaining=(window.decision_from,) if blocked else (),
        )
        return []

    def parse(self, window, extra_dockets=frozenset()):
        return iter(self.entries)


def list_entry(docket, list_date, decided, starred=False):
    return SourceRecord(
        source=config.BGER_LIST,
        source_key=f"{list_date}:{docket}",
        docket=docket,
        decision_date=decided,
        fields={"publication_date": list_date, "starred": starred, "division": docket.split("_")[0]},
        record={"list_date": list_date, "case": docket},
    )


@pytest.fixture
def run(db_conn, tmp_path):
    """run(files, bger=..., **kwargs) -> IngestReport, with daily files served from `files` (day -> rows)."""

    def _run(files, published=JULY, bger=None, mirror=None, **kwargs):
        downloads = FakeDownloads({day: parquet_bytes(rows) for day, rows in files.items()})
        daily = DailyFilesAdapter(snapshot_dir=tmp_path / "live", download=downloads)
        daily.today = "2026-12-31"
        server = mirror if mirror is not None else FakeES([])  # by default the mirror holds none of the rulings
        make_mirror = lambda root: EntscheidsucheAdapter(snapshot_dir=root, delay=0, http=server, sleep=lambda s: None)  # noqa: E731
        return ingest.ingest(
            db_conn, *published, daily=daily, bger=bger or FakeBger(tmp_path), mirror=make_mirror, **kwargs
        )

    return _run


def daily_row(docket, published, decided, text=GOOD):
    return old_row(docket, published=published, decided=decided, text=text)


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


TWO_NEW = {
    "2026-07-20": [daily_row("8C_5/2026", "2026-07-20", "2026-06-10")],  # decided inside the pinned window
    "2026-07-21": [daily_row("8C_6/2026", "2026-07-21", "2026-07-08")],  # decided after it
}


# --- adding ---------------------------------------------------------------------------------------------


def test_new_rulings_are_added_with_text_and_reported(db_conn, run):
    report = run(TWO_NEW)
    assert report.new_rulings == [
        {"docket": "8C_5/2026", "decision_date": "2026-06-10", "publication_date": "2026-07-20"},
        {"docket": "8C_6/2026", "decision_date": "2026-07-08", "publication_date": "2026-07-21"},
    ]
    assert (report.known_rulings, report.kept_existing, report.records_read) == (0, [], 2)
    late = ruling(db_conn, "8C_6/2026", "2026-07-08")
    assert late["in_window"] is False and late["field_sources"]["publication_date"] == config.SWISS_CASELAW
    assert db_conn.execute("SELECT count(*) FROM ruling_texts WHERE is_canonical").fetchone()[0] == 2
    assert db_conn.execute(
        "SELECT docket, published_from::text, published_to::text FROM ingested_rulings ORDER BY 1"
    ).fetchall() == [
        ("8C_5/2026", *JULY),
        ("8C_6/2026", *JULY),
    ]
    assert _count(db_conn, "raw_files") == 2  # the checksum of each daily file is recorded


def test_running_the_same_range_again_adds_nothing_and_changes_nothing(db_conn, run):
    run(TWO_NEW)
    snapshot = lambda: (  # noqa: E731
        db_conn.execute(
            "SELECT id, docket, decision_date, publication_date, field_sources FROM rulings ORDER BY id"
        ).fetchall(),
        db_conn.execute("SELECT id, source_key, ruling_id, status FROM source_records ORDER BY id").fetchall(),
        db_conn.execute("SELECT id, ruling_id, is_canonical, md5(text) FROM ruling_texts ORDER BY id").fetchall(),
    )
    before = snapshot()
    again = run(TWO_NEW)
    assert (again.new_rulings, again.known_rulings, again.kept_existing) == ([], 2, [])
    assert snapshot() == before
    assert _count(db_conn, "ingested_rulings") == 2


def test_only_the_new_ruling_is_added_when_the_range_overlaps_what_is_held(db_conn, run):
    run({"2026-07-20": TWO_NEW["2026-07-20"]}, published=("2026-07-20", "2026-07-20"))
    known = ruling(db_conn, "8C_5/2026", "2026-06-10")["id"]
    report = run(TWO_NEW)
    assert [r["docket"] for r in report.new_rulings] == ["8C_6/2026"] and report.known_rulings == 1
    assert ruling(db_conn, "8C_5/2026", "2026-06-10")["id"] == known and _count(db_conn, "rulings") == 2


# --- never overwriting ------------------------------------------------------------------------------------


def _attach_work(conn, ruling_id):
    run_id = conn.execute(
        "INSERT INTO model_runs (kind, models) VALUES ('summary', %s) RETURNING id",
        (Jsonb([{"name": "m", "role": "r"}]),),
    ).fetchone()[0]
    first = conn.execute(
        """INSERT INTO summaries (ruling_id, language, body, origin, run_id, is_current)
           VALUES (%s, 'de', 'Entwurf.', 'model', %s, false) RETURNING id""",
        (ruling_id, run_id),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO summaries (ruling_id, language, body, origin, parent_id, version)
           VALUES (%s, 'de', 'Korrigiert.', 'expert', %s, 2)""",
        (ruling_id, first),
    )
    triage = conn.execute(
        "INSERT INTO model_runs (kind, models) VALUES ('triage', %s) RETURNING id",
        (Jsonb([{"name": "m", "role": "r"}]),),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.9, true)", (ruling_id, triage)
    )
    conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'expert_override', 'not_relevant')", (ruling_id,)
    )


def _work(conn):
    return (
        conn.execute(
            "SELECT id, ruling_id, version, origin, body, is_current, parent_id FROM summaries ORDER BY id"
        ).fetchall(),
        conn.execute("SELECT ruling_id, score, relevant, is_current FROM predictions ORDER BY id").fetchall(),
        conn.execute("SELECT ruling_id, label_set, value FROM labels ORDER BY id").fetchall(),
    )


def test_a_source_sending_a_known_ruling_again_with_other_content_changes_nothing_and_is_reported(db_conn, run):
    run({"2026-07-20": TWO_NEW["2026-07-20"]}, published=("2026-07-20", "2026-07-20"))
    old = ruling(db_conn, "8C_5/2026", "2026-06-10")
    _attach_work(db_conn, old["id"])
    work = _work(db_conn)
    stored_text = db_conn.execute("SELECT md5(text) FROM ruling_texts WHERE ruling_id = %s", (old["id"],)).fetchall()

    # The next day's file carries the same ruling again, with another publication date and another text.
    next_day = {
        "2026-07-21": [daily_row("8C_5/2026", "2026-07-21", "2026-06-10", text=OTHER_TEXT), *TWO_NEW["2026-07-21"]]
    }
    report = run(next_day, published=("2026-07-21", "2026-07-21"))

    assert [r["docket"] for r in report.new_rulings] == ["8C_6/2026"] and report.known_rulings == 1
    assert report.kept_existing == [
        {
            "source": config.SWISS_CASELAW,
            "source_key": "bger_8C_5_2026",
            "docket": "8C_5/2026",
            "differs": ["fields", "text"],
        }
    ]
    now = ruling(db_conn, "8C_5/2026", "2026-06-10")
    assert (now["id"], now["publication_date"]) == (old["id"], "2026-07-20")
    assert (
        db_conn.execute("SELECT md5(text) FROM ruling_texts WHERE ruling_id = %s", (old["id"],)).fetchall()
        == stored_text
    )
    assert _work(db_conn) == work


def test_ground_truth_may_correct_a_lower_source_and_leaves_expert_work_alone(db_conn, run, tmp_path):
    run(TWO_NEW)  # publication date 20 July comes from Hugging Face (tier 3)
    old = ruling(db_conn, "8C_5/2026", "2026-06-10")
    _attach_work(db_conn, old["id"])
    work = _work(db_conn)
    bger = FakeBger(
        tmp_path, status="complete", entries=[list_entry("8C_5/2026", "2026-07-21", "2026-06-10", starred=True)]
    )
    report = run(TWO_NEW, bger=bger)
    now = ruling(db_conn, "8C_5/2026", "2026-06-10")
    assert (now["id"], now["publication_date"], now["starred"]) == (old["id"], "2026-07-21", True)
    assert now["field_sources"]["publication_date"] == config.BGER_LIST
    assert report.new_rulings == [] and _work(db_conn) == work


def test_a_lower_source_never_corrects_ground_truth(db_conn, run):
    # Held: a ruling whose publication date (16 July) comes from a bger.ch list, text from the mirror.
    build(
        db_conn,
        [
            R(
                config.BGER_LIST,
                "2026-07-16:8C_5/2026",
                docket="8C_5/2026",
                date="2026-06-10",
                publication_date="2026-07-16",
                starred=False,
            ),
            R(config.ENTSCHEIDSUCHE, "mirror", docket="8C_5/2026", date="2026-06-10", text=GOOD),
        ],
    )
    old = ruling(db_conn, "8C_5/2026", "2026-06-10")
    # Hugging Face claims 20 July and another text.
    report = run({"2026-07-20": [daily_row("8C_5/2026", "2026-07-20", "2026-06-10", text=OTHER_TEXT)]})
    now = ruling(db_conn, "8C_5/2026", "2026-06-10")
    assert (now["id"], now["publication_date"]) == (old["id"], "2026-07-16")
    assert now["field_sources"]["publication_date"] == config.BGER_LIST
    canonical = db_conn.execute(
        "SELECT source FROM ruling_texts WHERE ruling_id = %s AND is_canonical", (old["id"],)
    ).fetchall()
    assert canonical == [(config.ENTSCHEIDSUCHE,)]
    assert report.new_rulings == [] and report.known_rulings == 1


# --- ground truth first -------------------------------------------------------------------------------------


def test_bger_is_asked_first_and_a_block_does_not_stop_the_ingest(db_conn, run, tmp_path):
    bger = FakeBger(tmp_path, status="blocked")
    report = run(TWO_NEW, bger=bger)
    assert bger.fetch_calls == 1
    assert report.status == "partial"
    assert report.bger == {
        "status": "blocked",
        "requested": 1,
        "days_missing": 1,
        "blocked_on": "2026-07-20",
        "records": 0,
    }
    assert len(report.new_rulings) == 2 and report.not_confirmed_by_bger == 2


def test_rulings_confirmed_by_a_bger_list_are_counted_as_confirmed(db_conn, run, tmp_path):
    entries = [
        list_entry("8C_5/2026", "2026-07-20", "2026-06-10", starred=True),
        list_entry("8C_7/2026", "2026-06-30", "2026-06-01"),  # a list outside the range: not part of this run
    ]
    report = run(TWO_NEW, bger=FakeBger(tmp_path, status="complete", entries=entries))
    assert report.status == "ok" and report.bger["records"] == 1
    assert [r["docket"] for r in report.new_rulings] == ["8C_5/2026", "8C_6/2026"]
    assert report.not_confirmed_by_bger == 1  # 8C_6/2026 is known from Hugging Face only
    confirmed = ruling(db_conn, "8C_5/2026", "2026-06-10")
    assert confirmed["starred"] is True and confirmed["field_sources"]["starred"] == config.BGER_LIST
    assert ruling(db_conn, "8C_7/2026", "2026-06-01") is None


def test_bger_failing_outright_is_reported_and_the_ingest_goes_on(db_conn, run, tmp_path):
    class Broken(FakeBger):
        def fetch(self, window):
            raise OSError("certificate verify failed")

    report = run(TWO_NEW, bger=Broken(tmp_path))
    assert report.bger == {"status": "failed", "error": "OSError: certificate verify failed", "records": 0}
    assert report.status == "partial" and len(report.new_rulings) == 2


# --- surviving a rebuild, and failing cleanly -----------------------------------------------------------------


def test_a_rebuild_keeps_ingested_rulings_decided_outside_its_window(db_conn, run):
    run(TWO_NEW)
    report = rec.reconcile(db_conn, config.DEFAULT_WINDOW, ingest.ingested_dockets(db_conn))
    assert report.rulings_removed == 0 and ruling(db_conn, "8C_6/2026", "2026-07-08") is not None
    # Without the list of ingested rulings the rebuild would drop it: that is what the table is for.
    assert rec.reconcile(db_conn, config.DEFAULT_WINDOW).rulings_removed == 1


def test_a_refused_run_leaves_the_database_as_it_was_and_is_recorded_as_failed(db_conn, run):
    run(TWO_NEW)
    held = ruling(db_conn, "8C_6/2026", "2026-07-08")["id"]
    _attach_work(db_conn, held)

    def counts():
        tables = ("rulings", "source_records", "ruling_texts", "ingested_rulings", "raw_files")
        return tuple(_count(db_conn, t) for t in tables)

    before = counts()
    db_conn.execute("DELETE FROM ingested_rulings")  # simulate a database that lost track of its ingested rulings
    new_day = {"2026-07-22": [daily_row("8C_8/2026", "2026-07-22", "2026-06-15")]}
    with pytest.raises(RuntimeError, match="8C_6/2026"):
        run(new_day, published=("2026-07-22", "2026-07-22"))
    after = counts()
    assert after == (before[0], before[1], before[2], 0, before[4])
    assert (
        ruling(db_conn, "8C_8/2026", "2026-06-15") is None and ruling(db_conn, "8C_6/2026", "2026-07-08")["id"] == held
    )
    assert db_conn.execute("SELECT status FROM ingest_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "failed"


def test_range_must_not_end_before_it_starts(db_conn, run):
    with pytest.raises(ValueError):
        run({}, published=("2026-07-21", "2026-07-20"))
    assert _count(db_conn, "ingest_runs") == 0


# --- "since the last ingest" ---------------------------------------------------------------------------------


def test_since_last_starts_before_the_end_of_the_last_ingest_and_ends_yesterday(db_conn, run):
    run(TWO_NEW)  # ended on 21 July
    assert ingest.since_last_range(db_conn, today=date(2026, 8, 10)) == ("2026-07-07", "2026-08-09")
    assert ingest.since_last_range(db_conn, today=date(2026, 8, 10), overlap_days=0) == ("2026-07-21", "2026-08-09")


def test_since_last_without_an_earlier_ingest_starts_from_the_newest_publication_date_held(db_conn):
    build(
        db_conn,
        [
            R(config.BGER_LIST, "2026-01-14:8C_72/2025", publication_date="2026-01-14", starred=False),
            R(config.SWISS_CASELAW, "hf", text=GOOD),
        ],
    )
    assert ingest.since_last_range(db_conn, today=date(2026, 2, 1)) == ("2025-12-31", "2026-01-31")


def test_since_last_on_an_empty_database_asks_for_a_range(db_conn):
    with pytest.raises(ValueError, match="date range"):
        ingest.since_last_range(db_conn, today=date(2026, 2, 1))


def test_a_failed_run_does_not_move_the_starting_point(db_conn, run):
    run(TWO_NEW)
    db_conn.execute(
        "INSERT INTO ingest_runs (command, params, status) VALUES ('ingest', %s, 'failed')",
        (Jsonb({"published_to": "2026-09-30"}),),
    )
    assert ingest.last_published_to(db_conn) == "2026-07-21"


# --- the loader's add-only mode --------------------------------------------------------------------------------


def test_add_only_load_inserts_new_records_and_never_rewrites_stored_ones(db_conn):
    load.load_source_records(db_conn, [R(config.SWISS_CASELAW, "a", text=GOOD, language="de")])
    kept: list = []
    counts = load.load_source_records(
        db_conn,
        [
            R(config.SWISS_CASELAW, "a", text=OTHER_TEXT, language="fr"),  # stored already, now different
            R(config.SWISS_CASELAW, "b", docket="8C_73/2025", text=GOOD),  # new
        ],
        add_only=True,
        kept=kept,
    )
    assert (counts["read"], counts["inserted"], counts["updated"], counts["kept_existing"], counts["unchanged"]) == (
        2,
        1,
        0,
        1,
        0,
    )
    assert kept == [
        {"source": config.SWISS_CASELAW, "source_key": "a", "docket": "8C_72/2025", "differs": ["fields", "text"]}
    ]
    assert (
        db_conn.execute("SELECT fields ->> 'language' FROM source_records WHERE source_key = 'a'").fetchone()[0] == "de"
    )
    stored = db_conn.execute(
        "SELECT t.text FROM ruling_texts t JOIN source_records s ON s.id = t.source_record_id WHERE s.source_key = 'a'"
    ).fetchone()[0]
    assert stored == GOOD


# --- the mirror: a second, independent text ---------------------------------------------------------------------


def mirror_hit(docket, decided, text=GOOD, language="de"):
    """One ruling as the mirror's search endpoint returns it (shape of the saved fixture pages)."""
    key = f"CH_BGer_008_{docket.replace('_', '-').replace('/', '-')}_{decided}"
    return {
        "_id": key,
        "_source": {
            "id": key,
            "hierarchy": ["CH", "CH_BGer", "CH_BGer_008"],
            "date": decided,
            "reference": [docket],
            "language": language,
            "attachment": {"content": text, "content_length": len(text), "language": language},
        },
    }


def test_new_rulings_get_a_second_text_from_the_mirror_and_it_becomes_the_canonical_one(db_conn, run):
    server = FakeES([mirror_hit("8C_5/2026", "2026-06-10"), mirror_hit("8C_6/2026", "2026-07-08")])
    report = run(TWO_NEW, mirror=server)
    assert report.mirror == {"status": "complete", "asked": 2, "found": 2, "other_decision_date": 0, "requests": 1}
    assert (len(report.new_rulings), report.new_with_two_texts, report.text_mismatches) == (2, 2, [])
    new = ruling(db_conn, "8C_5/2026", "2026-06-10")
    texts = db_conn.execute(
        "SELECT source, is_canonical FROM ruling_texts WHERE ruling_id = %s ORDER BY 1", (new["id"],)
    ).fetchall()
    assert texts == [(config.ENTSCHEIDSUCHE, True), (config.SWISS_CASELAW, False)]
    # The mirror was asked by case number only, never for a whole period.
    filters = server.calls[0]["body"]["query"]["bool"]["filter"]
    assert {"terms": {"reference": ["8C_5/2026", "8C_6/2026"]}} in filters
    assert db_conn.execute("SELECT path FROM raw_files WHERE source = %s", (config.ENTSCHEIDSUCHE,)).fetchall() == [
        (f"mirror/run_{report.run_id}/entscheidsuche/extras/page_001.json",)
    ]


def test_texts_that_differ_between_the_two_sources_are_flagged(db_conn, run):
    server = FakeES([mirror_hit("8C_5/2026", "2026-06-10", text=OTHER_TEXT), mirror_hit("8C_6/2026", "2026-07-08")])
    report = run(TWO_NEW, mirror=server)
    assert report.text_mismatches == ["8C_5/2026"] and report.new_with_two_texts == 2
    assert ruling(db_conn, "8C_5/2026", "2026-06-10")["flags"].get("text_mismatch") is True
    assert db_conn.execute("SELECT count(*) FROM conflicts WHERE kind = 'text_mismatch'").fetchone()[0] == 1


def test_a_ruling_the_mirror_does_not_have_yet_is_asked_for_again_on_a_later_run(db_conn, run):
    first = run(TWO_NEW, mirror=FakeES([mirror_hit("8C_5/2026", "2026-06-10")]))
    assert (first.mirror["asked"], first.mirror["found"], first.new_with_two_texts) == (2, 1, 1)
    held = ruling(db_conn, "8C_6/2026", "2026-07-08")["id"]

    later = FakeES([mirror_hit("8C_5/2026", "2026-06-10"), mirror_hit("8C_6/2026", "2026-07-08")])
    second = run(TWO_NEW, mirror=later)
    assert (second.mirror["asked"], second.mirror["found"]) == (1, 1)  # only the ruling still without a mirror text
    assert later.calls[0]["body"]["query"]["bool"]["filter"][1] == {"terms": {"reference": ["8C_6/2026"]}}
    assert second.new_rulings == [] and ruling(db_conn, "8C_6/2026", "2026-07-08")["id"] == held
    canonical = db_conn.execute(
        "SELECT source FROM ruling_texts WHERE ruling_id = %s AND is_canonical", (held,)
    ).fetchall()
    assert canonical == [(config.ENTSCHEIDSUCHE,)]
    assert (
        db_conn.execute("SELECT count(*) FROM raw_files WHERE source = %s", (config.ENTSCHEIDSUCHE,)).fetchone()[0] == 2
    )


def test_another_decision_under_the_same_case_number_is_not_brought_in(db_conn, run):
    server = FakeES([mirror_hit("8C_5/2026", "2026-02-02"), mirror_hit("8C_5/2026", "2026-06-10")])
    report = run({"2026-07-20": TWO_NEW["2026-07-20"]}, published=("2026-07-20", "2026-07-20"), mirror=server)
    assert (report.mirror["found"], report.mirror["other_decision_date"]) == (1, 1)
    assert ruling(db_conn, "8C_5/2026", "2026-02-02") is None and _count(db_conn, "rulings") == 1


def test_the_mirror_refusing_is_reported_and_the_rulings_are_still_added(db_conn, run):
    report = run(TWO_NEW, mirror=FakeES([], status=[403]))
    assert report.mirror["status"] == "failed" and "EntscheidsucheRefused" in report.mirror["error"]
    assert report.status == "partial" and len(report.new_rulings) == 2 and report.new_with_two_texts == 0


def test_the_mirror_is_not_asked_when_every_ruling_of_the_range_already_has_its_text(db_conn, run):
    hits = [mirror_hit("8C_5/2026", "2026-06-10"), mirror_hit("8C_6/2026", "2026-07-08")]
    run(TWO_NEW, mirror=FakeES(hits))
    again = FakeES(hits)
    report = run(TWO_NEW, mirror=again)
    assert again.calls == [] and report.mirror == {
        "status": "complete",
        "asked": 0,
        "found": 0,
        "other_decision_date": 0,
    }

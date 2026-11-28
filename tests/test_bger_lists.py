"""bger.ch daily-list adapter. Offline: fixture pages only, urllib is mocked, no database."""

from __future__ import annotations

import io
import shutil
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from suva_data import config
from suva_data.config import Window
from suva_data.models import DOCKET_RE, SourceRecord
from suva_data.sources import bger_lists
from suva_data.sources.bger_lists import BgerListAdapter, BlockedError, fetch_day, parse_day

FIXTURES = Path(__file__).parent / "fixtures" / "bger_lists"
PAGE = (FIXTURES / "20251212.html").read_text(encoding="utf-8")
BLOCK_PAGE = (FIXTURES / "block_page.html").read_text(encoding="utf-8")
ALL = Window("2025-01-01", "2026-12-31")
URL_458 = (
    "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php"
    "?highlight_docid=aza://18-11-2025-8C_458-2025&lang=de&zoom=&type=show_document"
)


def page_for(day: date) -> str:
    """The fixture page re-dated to another list day (same entries)."""
    return PAGE.replace("<b>12.12.2025</b>", f"<b>{day:%d.%m.%Y}</b>")


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    """A snapshot dir with the weekday page and the empty weekend page."""
    d = tmp_path / "bger_list"
    d.mkdir()
    for name in ("20251212.html", "20251213.html"):
        shutil.copy(FIXTURES / name, d / name)
    return d


class FakeSite:
    """Stands in for urllib.request.urlopen: serves cp1252 list pages, or blocks."""

    def __init__(
        self, block_from_request: int | None = None, block_with: str = "page", fail_days: tuple[str, ...] = ()
    ):
        self.block_from_request, self.block_with, self.fail_days = block_from_request, block_with, fail_days
        self.requests: list[urllib.request.Request] = []

    def days(self) -> list[str]:
        return [r.full_url.split("date=")[1][:8] for r in self.requests]

    def __call__(self, req, context=None, timeout=None):
        self.requests.append(req)
        assert context is not None, "the TLS context with the intermediate certificate must be passed"
        ymd = req.full_url.split("date=")[1][:8]
        if self.block_from_request is not None and len(self.requests) >= self.block_from_request:
            if self.block_with == "page":
                return io.BytesIO(BLOCK_PAGE.encode("utf-8"))
            raise urllib.error.HTTPError(req.full_url, int(self.block_with), "Forbidden", None, None)
        if ymd in self.fail_days:
            raise urllib.error.URLError("connection reset")
        return io.BytesIO(page_for(date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))).encode("cp1252"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any un-mocked request fails the test; sleeping is recorded instead of done."""

    def refuse(*a, **k):
        raise AssertionError("network access attempted in a test")

    monkeypatch.setattr(bger_lists.urllib.request, "urlopen", refuse)
    sleeps: list[float] = []
    monkeypatch.setattr(bger_lists.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture
def site(monkeypatch):
    def install(**kw) -> FakeSite:
        fake = FakeSite(**kw)
        monkeypatch.setattr(bger_lists.urllib.request, "urlopen", fake)
        return fake

    return install


# --- parse_day ---------------------------------------------------------------------------------


def test_parse_day_reads_list_date_and_entries():
    list_date, entries = parse_day(PAGE)
    assert list_date == "2025-12-12"
    assert [e.case for e in entries] == [
        "1C_594/2025",
        "4A_508/2025",
        "8C_313/2024",
        "8C_458/2025",
        "8C_648/2025",
        "7B_65/2023",
    ]
    assert all(e.list_date == "2025-12-12" for e in entries)


def test_parse_day_empty_and_block_pages_have_no_list():
    assert parse_day((FIXTURES / "20251213.html").read_text(encoding="utf-8")) == (None, [])
    assert parse_day(BLOCK_PAGE) == (None, [])


# --- parse -------------------------------------------------------------------------------------


def test_parse_all_fields_of_a_starred_entry(snapshot):
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    assert adapter.name == config.BGER_LIST == "bger_list"
    by_docket = {r.docket: r for r in adapter.parse(ALL)}
    assert len(by_docket) == 6
    r = by_docket["8C_458/2025"]
    assert r == SourceRecord(
        source="bger_list",
        source_key="2025-12-12:8C_458/2025",
        docket="8C_458/2025",
        decision_date="2025-11-18",
        fields={
            "publication_date": "2025-12-12",
            "starred": True,
            "division": "8C",
            "area": "Unfallversicherung",  # the star is not part of the area
            "subject": "Unfallversicherung",
            "official_url": URL_458,
        },
        record={
            "list_date": "2025-12-12",
            "decision_date": "2025-11-18",
            "case": "8C_458/2025",
            "division": "8C",
            "starred": True,
            "area": "Unfallversicherung",
            "subject": "Unfallversicherung",
            "url": URL_458,
        },
        text=None,
        raw_file="bger_list/20251212.html",
    )
    assert adapter.problems == []


def test_parse_star_is_true_or_false_never_missing(snapshot):
    starred = {r.docket: r.fields["starred"] for r in BgerListAdapter(snapshot_dir=snapshot).parse(ALL)}
    assert starred == {
        "1C_594/2025": False,
        "4A_508/2025": False,
        "8C_313/2024": False,
        "8C_458/2025": True,
        "8C_648/2025": False,
        "7B_65/2023": True,
    }
    assert all(type(v) is bool for v in starred.values())


def test_parse_french_entries_keep_accents_and_entities(snapshot):
    by_docket = {r.docket: r for r in BgerListAdapter(snapshot_dir=snapshot).parse(ALL)}
    fr = by_docket["7B_65/2023"]
    assert fr.fields["area"] == "Procédure pénale"
    assert (
        fr.fields["subject"]
        == "Confiscation et créance compensatrice (classement de la procédure); indemnisation de tiers"
    )
    assert by_docket["8C_648/2025"].fields["area"] == "Santé & sécurité sociale"  # &amp; unescaped


def test_parse_records_respect_the_contract(snapshot):
    for r in BgerListAdapter(snapshot_dir=snapshot).parse(ALL):
        assert DOCKET_RE.match(r.docket)
        assert set(r.fields) <= set(config.CANONICAL_FIELDS)
        assert "" not in r.fields.values() and "" not in r.record.values()
        assert r.text is None
        assert r.source_key == f"{r.fields['publication_date']}:{r.docket}"
        assert r.decision_date <= r.fields["publication_date"]


def test_parse_omits_unknown_values_instead_of_empty_strings(snapshot):
    page = PAGE.replace("<CITE>Invalidenversicherung</CITE>", "").replace(
        '<TD style="padding-left: 1cm;">Invalidenversicherung</TD>', "<TD></TD>"
    )
    (snapshot / "20251212.html").write_text(page, encoding="utf-8")
    r = {r.docket: r for r in BgerListAdapter(snapshot_dir=snapshot).parse(ALL)}["8C_313/2024"]
    assert "area" not in r.fields and "subject" not in r.fields
    assert "area" not in r.record and "subject" not in r.record
    assert r.fields["starred"] is False


def test_parse_filters_by_decision_date_not_list_date(snapshot):
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    # decision dates on the page: 11.11, 12.11, 13.11, 18.11, 01.12, 05.12 (all listed on 12.12)
    assert [r.docket for r in adapter.parse(Window("2025-11-12", "2025-11-18"))] == [
        "4A_508/2025",
        "8C_313/2024",
        "8C_458/2025",
    ]
    assert [r.docket for r in adapter.parse(Window("2025-12-01", "2025-12-05"))] == ["7B_65/2023", "8C_648/2025"]
    # the list date itself is in this window, no decision date is
    assert list(adapter.parse(Window("2025-12-06", "2025-12-31"))) == []


def test_parse_extra_dockets_are_kept_outside_the_window(snapshot):
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    recs = list(adapter.parse(Window("2025-12-01", "2025-12-05"), frozenset({"8C_458/2025", "9C_1/2020"})))
    assert [r.docket for r in recs] == ["7B_65/2023", "8C_458/2025", "8C_648/2025"]
    assert recs[1].decision_date == "2025-11-18"


def test_parse_is_deterministic_and_sorted_by_source_key(snapshot):
    (snapshot / "20251215.html").write_text(page_for(date(2025, 12, 15)), encoding="utf-8")
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    first, second = list(adapter.parse(ALL)), list(adapter.parse(ALL))
    assert first == second
    keys = [r.source_key for r in first]
    assert keys == sorted(keys) and len(set(keys)) == len(keys) == 12


def test_parse_ruling_on_two_lists_yields_two_records(snapshot):
    (snapshot / "20251215.html").write_text(page_for(date(2025, 12, 15)), encoding="utf-8")
    recs = [r for r in BgerListAdapter(snapshot_dir=snapshot).parse(ALL) if r.docket == "8C_458/2025"]
    assert [r.source_key for r in recs] == ["2025-12-12:8C_458/2025", "2025-12-15:8C_458/2025"]
    assert [r.fields["publication_date"] for r in recs] == ["2025-12-12", "2025-12-15"]
    assert [r.raw_file for r in recs] == ["bger_list/20251212.html", "bger_list/20251215.html"]


def test_parse_skips_and_reports_page_with_mismatching_list_date(snapshot):
    # the site answered the request for 16.12 with the list of 12.12
    shutil.copy(FIXTURES / "20251212.html", snapshot / "20251216.html")
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    recs = list(adapter.parse(ALL))
    assert {r.raw_file for r in recs} == {"bger_list/20251212.html"} and len(recs) == 6
    assert adapter.problems == [
        {
            "kind": "list_date_mismatch",
            "file_date": "2025-12-16",
            "list_date": "2025-12-12",
            "entries": 6,
            "raw_file": "bger_list/20251216.html",
        }
    ]


def test_parse_reports_block_page_found_in_snapshot(snapshot):
    shutil.copy(FIXTURES / "block_page.html", snapshot / "20251217.html")
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    assert len(list(adapter.parse(ALL))) == 6
    assert adapter.problems == [{"kind": "block_page", "raw_file": "bger_list/20251217.html"}]


def test_parse_reports_invalid_docket_and_normalises_variants(snapshot):
    page = PAGE.replace(">4A_508/2025</A>", ">Verfügung ohne Nummer</A>").replace(
        ">1C_594/2025</A>", ">1C_0594/2025</A>"
    )
    (snapshot / "20251212.html").write_text(page, encoding="utf-8")
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    recs = {r.docket: r for r in adapter.parse(ALL)}
    assert len(recs) == 5 and "1C_594/2025" in recs
    assert recs["1C_594/2025"].record["case"] == "1C_0594/2025"  # raw string kept
    kinds = {p["kind"]: p for p in adapter.problems}
    assert set(kinds) == {"invalid_docket", "docket_normalised"}
    assert kinds["invalid_docket"]["case"] == "Verfügung ohne Nummer"
    assert kinds["invalid_docket"]["raw_file"] == "bger_list/20251212.html"
    assert kinds["docket_normalised"]["docket"] == "1C_594/2025"


def test_parse_same_docket_twice_on_one_list_keeps_both(snapshot):
    page = PAGE.replace(">4A_508/2025</A>", ">8C_458/2025</A>")
    (snapshot / "20251212.html").write_text(page, encoding="utf-8")
    adapter = BgerListAdapter(snapshot_dir=snapshot)
    keys = [r.source_key for r in adapter.parse(ALL) if r.docket == "8C_458/2025"]
    assert keys == ["2025-12-12:8C_458/2025", "2025-12-12:8C_458/2025#2"]
    assert [p["kind"] for p in adapter.problems] == ["duplicate_source_key"]


def test_parse_missing_snapshot_dir_yields_nothing(tmp_path):
    assert list(BgerListAdapter(snapshot_dir=tmp_path / "nope").parse(ALL)) == []


# --- fetch (urllib mocked) ---------------------------------------------------------------------

WEEK = Window("2025-12-08", "2025-12-12")  # Mon–Fri; with look-ahead 4: + Mon 15, Tue 16


def test_fetch_skips_weekends_and_days_already_in_snapshot(snapshot, site, no_network):
    fake = site()
    adapter = BgerListAdapter(snapshot_dir=snapshot, lookahead_days=4, delay_s=2.0, today=date(2026, 1, 1))
    written = adapter.fetch(WEEK)
    assert fake.days() == [
        "20251208",
        "20251209",
        "20251210",
        "20251211",
        "20251215",
        "20251216",
    ]  # no 12 (present), no 13/14
    assert written == [f"bger_list/{d}.html" for d in fake.days()]
    assert all((snapshot.parent / w).exists() for w in written)
    res = adapter.last_fetch
    assert (res.status, res.requested, res.already_present, res.remaining, res.errors) == ("complete", 6, 1, (), ())
    assert res.written == tuple(written)
    assert no_network == [2.0] * 5  # a delay between requests, none before the first
    assert {r.get_header("User-agent") for r in fake.requests} == {config.USER_AGENT}
    assert all(
        r.full_url == bger_lists.URL.format(d=date(2025, 12, int(d[6:]))) for r, d in zip(fake.requests, fake.days())
    )
    # second run: nothing left to do, no request
    assert adapter.fetch(WEEK) == [] and len(fake.requests) == 6
    assert adapter.last_fetch.status == "complete" and adapter.last_fetch.already_present == 7


def test_fetch_decodes_cp1252_and_stores_utf8(snapshot, site):
    site()
    adapter = BgerListAdapter(snapshot_dir=snapshot, lookahead_days=0, today=date(2026, 1, 1))
    adapter.fetch(Window("2025-12-11", "2025-12-11"))
    stored = (snapshot / "20251211.html").read_text(encoding="utf-8")
    assert "Procédure pénale*" in stored and "Rechtsöffnung" in stored
    recs = [r for r in adapter.parse(ALL) if r.fields["publication_date"] == "2025-12-11"]
    assert len(recs) == 6


@pytest.mark.parametrize("block_with", ["page", "403", "429"])
def test_fetch_stops_at_first_block_and_never_stores_the_block_page(snapshot, site, block_with):
    fake = site(block_from_request=3, block_with=block_with)
    adapter = BgerListAdapter(snapshot_dir=snapshot, lookahead_days=4, today=date(2026, 1, 1))
    written = adapter.fetch(WEEK)  # must not raise
    assert written == ["bger_list/20251208.html", "bger_list/20251209.html"]
    assert fake.days() == ["20251208", "20251209", "20251210"]  # stopped: no request after the block
    res = adapter.last_fetch
    assert res.status == "blocked" and res.blocked_on == "2025-12-10"
    assert res.remaining == ("2025-12-10", "2025-12-11", "2025-12-15", "2025-12-16")
    assert sorted(p.name for p in snapshot.iterdir()) == [
        "20251208.html",
        "20251209.html",
        "20251212.html",
        "20251213.html",
    ]
    assert not any("Incapsula" in p.read_text(encoding="utf-8") for p in snapshot.iterdir())


def test_fetch_blocked_on_first_request_writes_nothing(tmp_path, site):
    fake = site(block_from_request=1)
    adapter = BgerListAdapter(snapshot_dir=tmp_path / "bger_list", today=date(2026, 12, 1))
    assert adapter.fetch(config.DEFAULT_WINDOW) == []
    assert len(fake.requests) == 1 and adapter.last_fetch.status == "blocked"
    assert not (tmp_path / "bger_list").exists() or list((tmp_path / "bger_list").iterdir()) == []


def test_fetch_reports_other_errors_as_gaps_and_goes_on(snapshot, site):
    fake = site(fail_days=("20251209",))
    adapter = BgerListAdapter(snapshot_dir=snapshot, lookahead_days=0, today=date(2026, 1, 1))
    written = adapter.fetch(WEEK)
    assert written == ["bger_list/20251208.html", "bger_list/20251210.html", "bger_list/20251211.html"]
    assert len(fake.requests) == 4
    res = adapter.last_fetch
    assert res.status == "incomplete" and res.remaining == ("2025-12-09",)
    assert res.errors[0][0] == "2025-12-09" and "connection reset" in res.errors[0][1]
    assert not (snapshot / "20251209.html").exists()


def test_fetch_never_requests_today_or_future_days(snapshot, site):
    fake = site()
    adapter = BgerListAdapter(snapshot_dir=snapshot, lookahead_days=4, today=date(2025, 12, 10))
    adapter.fetch(WEEK)
    assert fake.days() == ["20251208", "20251209"]


def test_needed_days_cover_window_plus_default_lookahead():
    days = BgerListAdapter(snapshot_dir=FIXTURES).needed_days(config.DEFAULT_WINDOW)
    assert days[0] == date(2025, 10, 1) and days[-1] == date(2026, 9, 30)  # 2026-06-30 + 92 days
    assert all(d.weekday() < 5 for d in days)


def test_fetch_day_raises_blocked_and_reads_snapshot_first(snapshot, site):
    text, fetched = fetch_day(date(2025, 12, 12), snapshot)  # present: no request (urlopen would fail the test)
    assert fetched is False and text == PAGE
    site(block_from_request=1)
    with pytest.raises(BlockedError):
        fetch_day(date(2025, 12, 11), snapshot)
    assert not (snapshot / "20251211.html").exists()


# --- coverage ----------------------------------------------------------------------------------


def test_coverage_reports_range_gaps_and_window_needs(snapshot):
    (snapshot / "20251217.html").write_text(page_for(date(2025, 12, 17)), encoding="utf-8")  # Wed
    (snapshot / "20251216.html").write_text("\n", encoding="utf-8")  # Tue fetched, no list
    cov = BgerListAdapter(snapshot_dir=snapshot).coverage(Window("2025-12-11", "2025-12-12"), lookahead_days=7)
    assert (cov.first_list_date, cov.last_list_date, cov.lists) == ("2025-12-12", "2025-12-17", 2)
    assert cov.missing_weekdays_in_range == 1  # Mon 15.12 was never fetched
    assert cov.weekdays_without_list_in_range == ("2025-12-16",)
    assert (cov.window_from, cov.window_to) == ("2025-12-11", "2025-12-19")
    assert cov.window_missing_weekdays == ("2025-12-11", "2025-12-15", "2025-12-18", "2025-12-19")
    assert cov.as_dict()["lists"] == 2


def test_coverage_of_empty_snapshot(tmp_path):
    cov = BgerListAdapter(snapshot_dir=tmp_path).coverage(Window("2025-12-12", "2025-12-12"), lookahead_days=0)
    assert (cov.first_list_date, cov.last_list_date, cov.lists, cov.missing_weekdays_in_range) == (None, None, 0, 0)
    assert cov.window_missing_weekdays == ("2025-12-12",)


# --- compatibility shim ------------------------------------------------------------------------


def test_shim_keeps_the_old_names(monkeypatch):
    monkeypatch.syspath_prepend(str(config.REPO / "src"))
    sys.modules.pop("bger_news", None)
    import bger_news

    assert bger_news.CACHE == config.SNAPSHOT_DIR / config.BGER_LIST
    assert bger_news.parse_day is parse_day and bger_news.Entry is bger_lists.Entry
    assert callable(bger_news.fetch_day) and callable(bger_news.crawl)
    list_date, entries = bger_news.parse_day(PAGE)
    assert list_date == "2025-12-12" and isinstance(entries[0], bger_news.Entry)


def test_shim_crawl_reads_the_snapshot_without_network(monkeypatch, snapshot):
    monkeypatch.syspath_prepend(str(config.REPO / "src"))
    sys.modules.pop("bger_news", None)
    import bger_news

    monkeypatch.setattr(bger_news, "CACHE", snapshot)
    rows = bger_news.crawl(date(2025, 12, 12), date(2025, 12, 14))  # Fri + weekend
    assert len(rows) == 6 and rows[3]["case"] == "8C_458/2025" and rows[3]["starred"] is True

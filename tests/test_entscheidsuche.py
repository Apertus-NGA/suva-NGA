"""Offline tests for the entscheidsuche.ch adapter. No network, no database.

Fixtures (tests/fixtures/entscheidsuche/) are real hits saved by the adapter on 2026-11-27, texts untouched:
    2025-12/page_001.json, page_002.json   5 rulings decided in December 2025 (page size 3)
    2026-01/page_001.json                  1 ruling decided in January 2026
    extras/page_001.json                   1 gold-summary ruling decided before the window
    html_samples/<_id>.html                the raw per-ruling .html file of 8C_72/2025 (not a snapshot directory)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.suva_data import config, textnorm
from src.suva_data.config import Window
from src.suva_data.sources import entscheidsuche as es
from src.suva_data.sources.entscheidsuche import EntscheidsucheAdapter, EntscheidsucheError, EntscheidsucheRefused

FIXTURES = Path(__file__).parent / "fixtures"  # plays the role of SNAPSHOT_DIR
FIXTURE_ROOT = FIXTURES / "entscheidsuche"
WINDOW = Window("2025-12-01", "2026-01-31")
EXTRA_DOCKET = "8C_455/2025"  # decided 2025-08-27, outside WINDOW
IN_WINDOW_GOLD = "8C_72/2025"  # decided 2025-12-11, inside WINDOW
EXTRAS = frozenset({EXTRA_DOCKET, IN_WINDOW_GOLD})
FIXTURE_PAGE_SIZE = 3


def fixture_hits() -> list[dict]:
    return [h for p in sorted(FIXTURE_ROOT.glob("*/page_*.json")) for h in json.loads(p.read_text("utf-8"))["hits"]]


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class FakeES:
    """Just enough of the search endpoint: term/range/terms filters, must_not, sort, search_after, from/size."""

    def __init__(self, hits, descending=False, status=None, total_offset=0, refuse_search_after=False, fail_at=None):
        self.hits = hits
        self.descending = descending  # the server returning hits in another order
        self.status = status or []  # HTTP statuses to answer with before behaving normally
        self.total_offset = total_offset
        self.refuse_search_after = refuse_search_after
        self.fail_at = fail_at  # (request number, HTTP status)
        self.calls: list[dict] = []

    def __call__(self, url, body, headers, timeout):
        request = json.loads(body.decode("utf-8"))
        self.calls.append({"url": url, "body": request, "headers": headers, "timeout": timeout})
        if self.status:
            status = self.status.pop(0)
            if isinstance(status, Exception):
                raise status
            if status != 200:
                return status, b"<html>nope</html>"
        if self.fail_at and self.fail_at[0] == len(self.calls):
            return self.fail_at[1], b"<html>nope</html>"
        if self.refuse_search_after and "search_after" in request:
            return 200, json.dumps(
                {"error": {"root_cause": [{"type": "illegal_argument_exception"}]}, "status": 400}
            ).encode()

        bool_query = request["query"]["bool"]
        selected = [
            h
            for h in self.hits
            if all(self._matches(h["_source"], c) for c in bool_query.get("filter", []))
            and not any(self._matches(h["_source"], c) for c in bool_query.get("must_not", []))
        ]
        assert request["sort"] == [{"date": "asc"}, {"id": "asc"}]
        selected.sort(key=lambda h: (h["_source"]["date"], h["_id"]), reverse=self.descending)
        keys = [[h["_source"]["date"], h["_id"]] for h in selected]
        start = request.get("from", 0)
        if "search_after" in request:
            start = keys.index(request["search_after"]) + 1
        page = selected[start : start + request["size"]]
        answer = {
            "took": 7 + len(self.calls),  # noise that must not reach the saved files
            "timed_out": False,
            "_shards": {"total": 300, "successful": 300, "skipped": 0, "failed": 0},
            "hits": {
                "total": {"value": len(selected) + self.total_offset, "relation": "eq"},
                "max_score": None,
                "hits": [
                    {
                        "_index": "entscheidsuche.v2-ch_bger",
                        "_type": "_doc",
                        "_id": h["_id"],
                        "_score": None,
                        "_source": copy.deepcopy(h["_source"]),
                        "sort": [h["_source"]["date"], h["_id"]],
                    }
                    for h in page
                ],
            },
        }
        return 200, json.dumps(answer, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _matches(source, clause):
        if "term" in clause:
            return clause["term"]["hierarchy"] in source["hierarchy"]
        if "terms" in clause:
            return bool(set(clause["terms"]["reference"]) & set(source["reference"]))
        bounds = clause["range"]["date"]
        return bounds["gte"] <= source["date"] <= bounds["lte"]


def make_adapter(tmp_path, server, page_size=FIXTURE_PAGE_SIZE, sleeps=None):
    sleep = (lambda s: None) if sleeps is None else sleeps.append
    return EntscheidsucheAdapter(snapshot_dir=tmp_path, delay=0, http=server, sleep=sleep, page_size=page_size)


# ---------------------------------------------------------------------------------------- fetch


def test_month_ranges_are_clipped_to_the_window():
    assert es.month_ranges(Window("2025-11-15", "2026-01-10")) == [
        ("2025-11", "2025-11-15", "2025-11-30"),
        ("2025-12", "2025-12-01", "2025-12-31"),
        ("2026-01", "2026-01-01", "2026-01-10"),
    ]
    assert es.month_ranges(Window("2028-02-01", "2028-02-29")) == [("2028-02", "2028-02-01", "2028-02-29")]
    assert [m[0] for m in es.month_ranges(config.DEFAULT_WINDOW)] == [
        "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]  # fmt: skip


def test_paging_uses_search_after_and_stops_at_the_total(tmp_path):
    server = FakeES(fixture_hits())
    adapter = make_adapter(tmp_path, server, page_size=2)
    written = adapter.fetch(Window("2025-12-01", "2025-12-31"))

    bodies = [c["body"] for c in server.calls]
    assert len(bodies) == 3  # 5 hits at 2 per page: 2 + 2 + 1, and no extra request to find the end
    assert all(b["size"] == 2 for b in bodies)
    assert "search_after" not in bodies[0] and "from" not in bodies[0]
    december = sorted(h["_id"] for h in fixture_hits() if h["_source"]["date"].startswith("2025-12"))
    by_date = sorted(december, key=lambda i: (i[-10:], i))
    assert bodies[1]["search_after"] == [by_date[1][-10:], by_date[1]]
    assert bodies[2]["search_after"] == [by_date[3][-10:], by_date[3]]
    assert bodies[0]["query"] == es.month_query("2025-12-01", "2025-12-31")
    assert written == [f"entscheidsuche/2025-12/page_{n:03d}.json" for n in (1, 2, 3)]
    assert adapter.fetch_totals == {"2025-12": 5} and adapter.request_count == 3

    call = server.calls[0]
    assert call["url"] == config.ENTSCHEIDSUCHE_SEARCH_URL
    assert call["headers"]["User-Agent"] == config.USER_AGENT
    assert call["headers"]["Content-Type"] == "application/json"

    saved = [json.loads((tmp_path / w).read_text("utf-8")) for w in written]
    assert [h["_id"] for page in saved for h in page["hits"]] == december  # sorted by _id across the pages
    assert all(page["total"] == 5 and set(page) == {"query", "total", "hits"} for page in saved)
    assert all(set(h) == {"_id", "_source"} for page in saved for h in page["hits"])


def test_requests_are_spaced_by_the_delay(tmp_path):
    sleeps: list[float] = []
    adapter = EntscheidsucheAdapter(
        snapshot_dir=tmp_path, delay=1.5, http=FakeES(fixture_hits()), sleep=sleeps.append, page_size=2
    )
    adapter.fetch(WINDOW)
    assert adapter.request_count == 4  # 3 for December, 1 for January
    assert sleeps == [1.5, 1.5, 1.5]  # before every request except the very first


def test_saved_bytes_do_not_depend_on_server_order_and_match_the_fixtures(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert make_adapter(a, FakeES(fixture_hits())).fetch(WINDOW, EXTRAS) == [
        "entscheidsuche/2025-12/page_001.json",
        "entscheidsuche/2025-12/page_002.json",
        "entscheidsuche/2026-01/page_001.json",
        "entscheidsuche/extras/page_001.json",
    ]
    make_adapter(b, FakeES(list(reversed(fixture_hits())), descending=True)).fetch(WINDOW, EXTRAS)
    assert tree_bytes(a) == tree_bytes(b)
    assert tree_bytes(a / "entscheidsuche") == {
        k: v for k, v in tree_bytes(FIXTURE_ROOT).items() if not k.startswith("html_samples/")}  # fmt: skip

    page = (a / "entscheidsuche/2025-12/page_001.json").read_text("utf-8")
    assert not any(noise in page for noise in ('"took"', '"_shards"', '"_score"', '"sort"', '"search_after"', "\\u00"))
    assert json.loads(page)["hits"] == sorted(json.loads(page)["hits"], key=lambda h: h["_id"])


def test_extras_query_is_by_reference_and_excludes_the_window(tmp_path):
    server = FakeES(fixture_hits())
    adapter = make_adapter(tmp_path, server)
    adapter.fetch(WINDOW, EXTRAS)
    query = server.calls[-1]["body"]["query"]
    assert query["bool"]["filter"][1] == {"terms": {"reference": sorted(EXTRAS)}}
    assert query["bool"]["must_not"] == [{"range": {"date": {"gte": "2025-12-01", "lte": "2026-01-31"}}}]
    extras = json.loads((tmp_path / "entscheidsuche/extras/page_001.json").read_text("utf-8"))
    assert [h["_source"]["reference"] for h in extras["hits"]] == [[EXTRA_DOCKET]]  # 8C_72/2025 stays in its month
    assert adapter.fetch_totals["extras"] == 1


def test_extras_are_queried_in_batches(tmp_path):
    dockets = frozenset(f"8C_{n}/2025" for n in range(1, 121))
    queries = es.extras_queries(WINDOW, dockets)
    assert [len(q["bool"]["filter"][1]["terms"]["reference"]) for q in queries] == [50, 50, 20]
    server = FakeES(fixture_hits())
    make_adapter(tmp_path, server).fetch(Window("2026-01-01", "2026-01-31"), dockets | {EXTRA_DOCKET})
    assert len(server.calls) == 1 + 3
    # 8C_72/2025 (December) is among the 120 and outside this January window. Batches follow the sorted
    # (string order) case numbers, so both known rulings fall into the second batch.
    pages = [json.loads(p.read_text("utf-8")) for p in sorted((tmp_path / "entscheidsuche/extras").glob("*.json"))]
    assert [[h["_source"]["reference"][0] for h in page["hits"]] for page in pages] == [
        [],
        [EXTRA_DOCKET, IN_WINDOW_GOLD],
        [],
    ]
    assert [page["total"] for page in pages] == [0, 2, 0]  # an empty batch still leaves its (empty) page as proof


def test_complete_directories_are_skipped_without_any_request(tmp_path):
    make_adapter(tmp_path, FakeES(fixture_hits())).fetch(WINDOW, EXTRAS)
    before = tree_bytes(tmp_path)

    server = FakeES(fixture_hits())
    again = make_adapter(tmp_path, server)
    assert again.fetch(WINDOW, EXTRAS) == []
    assert server.calls == []
    assert tree_bytes(tmp_path) == before
    assert again.fetch_totals == {"2025-12": 5, "2026-01": 1, "extras": 1}


def test_only_the_incomplete_month_is_fetched_again(tmp_path):
    make_adapter(tmp_path, FakeES(fixture_hits())).fetch(WINDOW, EXTRAS)
    before = tree_bytes(tmp_path)
    (tmp_path / "entscheidsuche/2025-12/page_002.json").unlink()

    server = FakeES(fixture_hits())
    written = make_adapter(tmp_path, server).fetch(WINDOW, EXTRAS)
    assert written == ["entscheidsuche/2025-12/page_001.json", "entscheidsuche/2025-12/page_002.json"]
    assert len(server.calls) == 2
    assert tree_bytes(tmp_path) == before


def test_a_changed_window_refetches_the_clipped_month(tmp_path):
    make_adapter(tmp_path, FakeES(fixture_hits())).fetch(WINDOW)
    server = FakeES(fixture_hits())
    written = make_adapter(tmp_path, server).fetch(Window("2025-12-01", "2026-01-15"))
    assert written == ["entscheidsuche/2026-01/page_001.json"]  # December unchanged, January has a new range
    assert json.loads((tmp_path / written[0]).read_text("utf-8"))["query"] == es.month_query("2026-01-01", "2026-01-15")


@pytest.mark.parametrize("offset", [1, -1])
def test_total_mismatch_raises_and_writes_nothing(tmp_path, offset):
    adapter = make_adapter(tmp_path, FakeES(fixture_hits(), total_offset=offset))
    with pytest.raises(EntscheidsucheError, match="server reports"):
        adapter.fetch(WINDOW)
    assert tree_bytes(tmp_path) == {}


def test_refusal_raises_a_clear_error_and_leaves_no_partial_month(tmp_path):
    # January is asked after December; the refusal comes on December's second page.
    server = FakeES(fixture_hits(), fail_at=(2, 403))
    adapter = make_adapter(tmp_path, server)
    with pytest.raises(EntscheidsucheRefused, match="refused the request .HTTP 403."):
        adapter.fetch(WINDOW, EXTRAS)
    assert len(server.calls) == 2  # no retry, no further month
    assert tree_bytes(tmp_path) == {}


def test_refusal_keeps_months_that_were_already_complete(tmp_path):
    server = FakeES(fixture_hits(), fail_at=(3, 429))
    with pytest.raises(EntscheidsucheRefused, match="429"):
        make_adapter(tmp_path, server).fetch(WINDOW, EXTRAS)
    assert sorted(tree_bytes(tmp_path)) == [
        "entscheidsuche/2025-12/page_001.json",
        "entscheidsuche/2025-12/page_002.json",
    ]
    assert tree_bytes(tmp_path / "entscheidsuche/2025-12") == tree_bytes(FIXTURE_ROOT / "2025-12")


def test_server_errors_and_timeouts_are_retried_twice_with_backoff(tmp_path):
    sleeps: list[float] = []
    server = FakeES(fixture_hits(), status=[503, TimeoutError("timed out")])
    adapter = EntscheidsucheAdapter(snapshot_dir=tmp_path, delay=1.0, http=server, sleep=sleeps.append, page_size=100)
    adapter.fetch(Window("2025-12-01", "2025-12-31"))
    assert len(server.calls) == 3 and sleeps == [2.0, 4.0]
    assert adapter.fetch_totals == {"2025-12": 5}


def test_gives_up_after_two_retries(tmp_path):
    server = FakeES(fixture_hits(), status=[500, 502, 503, 200])
    with pytest.raises(EntscheidsucheError, match="giving up .* after 3 attempts: HTTP 503"):
        make_adapter(tmp_path, server).fetch(WINDOW)
    assert len(server.calls) == 3 and tree_bytes(tmp_path) == {}


def test_falls_back_to_from_size_when_search_after_is_refused(tmp_path):
    server = FakeES(fixture_hits(), refuse_search_after=True)
    make_adapter(tmp_path, server, page_size=2).fetch(Window("2025-12-01", "2025-12-31"))
    bodies = [c["body"] for c in server.calls]
    assert ["search_after" in b for b in bodies] == [False, True, False, False, False]
    assert [b.get("from") for b in bodies[2:]] == [None, 2, 4]
    assert sum(len(json.loads(p.read_text("utf-8"))["hits"]) for p in tmp_path.rglob("page_*.json")) == 5


def test_an_error_document_on_the_first_page_raises(tmp_path):
    def broken(url, body, headers, timeout):
        return 200, b'{"error": {"reason": "No mapping found for [id] in order to sort on"}}'

    with pytest.raises(EntscheidsucheError, match="search rejected"):
        make_adapter(tmp_path, broken).fetch(WINDOW)
    assert tree_bytes(tmp_path) == {}


def test_fetch_document_only_talks_to_entscheidsuche(tmp_path):
    adapter = make_adapter(tmp_path, FakeES([]))
    with pytest.raises(ValueError, match="another host"):
        adapter.fetch_document("https://www.bger.ch/ext/eurospider/live/de/php/aza/http/index.php")
    assert adapter.request_count == 0


# ---------------------------------------------------------------------------------------- parse


def parse_fixtures(window=WINDOW, extras=EXTRAS):
    adapter = EntscheidsucheAdapter(snapshot_dir=FIXTURES, http=None)  # parse must not need HTTP
    return adapter, list(adapter.parse(window, extras))


def test_parse_maps_the_fields():
    adapter, records = parse_fixtures()
    assert [r.source_key for r in records] == sorted(h["_id"] for h in fixture_hits())
    assert (
        len(records) == 7 and adapter.undetermined == [] and adapter.docket_notes == [] and adapter.repeated_ids == []
    )

    r = next(r for r in records if r.docket == IN_WINDOW_GOLD)
    assert r.source == config.ENTSCHEIDSUCHE == adapter.name
    assert r.source_key == "CH_BGer_008_8C-72-2025_2025-12-11"
    assert r.decision_date == "2025-12-11"
    assert r.fields == {"language": "fr", "division": "8C"}  # no subject, no official_url: the record has none
    assert r.raw_file.startswith("entscheidsuche/2025-12/page_00") and (FIXTURES / r.raw_file).is_file()
    assert r.record["reference"] == ["8C_72/2025"]
    assert r.record["title"]["de"].startswith("Bundesgericht ")  # the title stays in the record only
    assert (
        r.record["attachment"]["content_url"]
        == "https://entscheidsuche.ch/docs/CH_BGer/CH_BGer_008_8C-72-2025_2025-12-11.html"
    )
    assert "content" not in r.record["attachment"]
    json.dumps(r.record)  # JSON-serialisable

    for record in records:
        assert set(record.fields) <= set(config.CANONICAL_FIELDS)
        assert record.fields["division"] == record.docket.split("_")[0]
        assert record.source_key.endswith(record.decision_date)


def test_parse_returns_the_text_exactly_as_saved():
    before = tree_bytes(FIXTURE_ROOT)
    _, records = parse_fixtures()
    saved = {h["_id"]: h["_source"]["attachment"]["content"] for h in fixture_hits()}
    for record in records:
        assert record.text == saved[record.source_key]
        assert len(record.text) > 600
    assert any("\xa0" in r.text and "\n\n" in r.text for r in records)  # not whitespace-normalised
    assert tree_bytes(FIXTURE_ROOT) == before


def test_parse_applies_the_window_and_the_extras():
    _, both = parse_fixtures()
    assert sorted(r.decision_date[:7] for r in both) == ["2025-08"] + ["2025-12"] * 5 + ["2026-01"]

    _, no_extras = parse_fixtures(extras=frozenset())
    assert len(no_extras) == 6 and all(WINDOW.contains(r.decision_date) for r in no_extras)

    _, december = parse_fixtures(window=Window("2025-12-01", "2025-12-31"), extras=frozenset())
    assert len(december) == 5

    _, one_day = parse_fixtures(window=Window("2025-12-11", "2025-12-11"), extras=frozenset({EXTRA_DOCKET}))
    assert sorted(r.docket for r in one_day) == sorted([EXTRA_DOCKET, IN_WINDOW_GOLD])

    _, only_extras = parse_fixtures(window=Window("2030-01-01", "2030-01-31"))
    assert sorted(r.docket for r in only_extras) == sorted(EXTRAS)  # extras are found wherever they were saved


def test_parse_is_deterministic_and_does_not_deduplicate_rulings(tmp_path):
    hits = fixture_hits()
    twin = copy.deepcopy(next(h for h in hits if h["_source"]["reference"] == [IN_WINDOW_GOLD]))
    twin["_id"] = twin["_source"]["id"] = "CH_BGer_008_8C-72-2025_2025-12-11_bis"  # same docket + date, another id
    write_page(
        tmp_path, "2025-12", hits[:3] + [twin] + [h for h in hits if h["_source"]["reference"] == [IN_WINDOW_GOLD]]
    )
    adapter = EntscheidsucheAdapter(snapshot_dir=tmp_path)
    first, second = list(adapter.parse(WINDOW)), list(adapter.parse(WINDOW))
    assert first == second and [r.source_key for r in first] == sorted(r.source_key for r in first)
    assert [r.docket for r in first].count(IN_WINDOW_GOLD) == 2


def write_page(root: Path, dirname: str, hits: list[dict], number: int = 1) -> None:
    directory = root / "entscheidsuche" / dirname
    directory.mkdir(parents=True, exist_ok=True)
    page = {"query": {}, "total": len(hits), "hits": sorted(hits, key=lambda h: h["_id"])}
    (directory / f"page_{number:03d}.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")


def test_parse_handles_several_references_none_and_unusable_ones(tmp_path):
    base = next(h for h in fixture_hits() if h["_source"]["reference"] == [IN_WINDOW_GOLD])

    def variant(new_id, reference):
        hit = copy.deepcopy(base)
        hit["_id"] = hit["_source"]["id"] = new_id
        hit["_source"]["reference"] = reference
        return hit

    joined = variant("CH_BGer_008_8C-72-2025_2025-12-11", ["8C_80/2025", "8C_72/2025"])
    no_reference = variant("CH_BGer_009_9C-5-2025_2025-12-11", [])
    disagree = variant("CH_BGer_008_8C-7-2025_2025-12-11", ["8C_8/2025"])
    hopeless = variant("CH_BGer_999_unknown_2025-12-11", ["Verfügung vom 11.12.2025"])
    joined_outside = variant("CH_BGer_008_8C-100-2024_2024-05-02", ["8C_100/2024", "8C_101/2024"])
    joined_outside["_source"]["date"] = "2024-05-02"
    write_page(tmp_path, "2025-12", [joined, no_reference, disagree, hopeless])
    write_page(tmp_path, "extras", [joined_outside])

    adapter = EntscheidsucheAdapter(snapshot_dir=tmp_path)
    records = {r.source_key: r for r in adapter.parse(WINDOW, frozenset({"8C_101/2024"}))}

    assert records[joined["_id"]].docket == "8C_72/2025"  # the id decides between several references
    assert records[joined["_id"]].record["reference"] == ["8C_80/2025", "8C_72/2025"]  # all of them are kept
    assert records[no_reference["_id"]].docket == "9C_5/2025"
    assert records[no_reference["_id"]].fields["division"] == "9C"
    assert records[disagree["_id"]].docket == "8C_8/2025"  # a single reference wins, the disagreement is noted
    # found through its second case number, although the docket is the first one
    assert records[joined_outside["_id"]].docket == "8C_100/2024"
    assert records[joined_outside["_id"]].raw_file == "entscheidsuche/extras/page_001.json"

    assert hopeless["_id"] not in records  # cannot be a SourceRecord (docket is mandatory) ...
    assert adapter.undetermined == [  # ... but it is reported, not dropped silently
        {"source_key": hopeless["_id"], "decision_date": "2025-12-11", "reference": ["Verfügung vom 11.12.2025"],
         "raw_file": "entscheidsuche/2025-12/page_001.json"}
    ]  # fmt: skip
    notes = {n["source_key"]: n["note"] for n in adapter.docket_notes}
    assert notes == {
        joined["_id"]: "2 references: docket taken from id",
        no_reference["_id"]: "no reference: docket taken from id",
        disagree["_id"]: "reference 8C_8/2025 != id 8C_7/2025",
        hopeless["_id"]: "1 references: no case number found",
        joined_outside["_id"]: "2 references: docket taken from id",
    }
    assert len(records) + len(adapter.undetermined) == 5  # every hit is accounted for


def test_parse_reads_a_ruling_saved_in_two_directories_once(tmp_path):
    hit = next(h for h in fixture_hits() if h["_source"]["reference"] == [IN_WINDOW_GOLD])
    write_page(tmp_path, "2025-12", [hit])
    write_page(tmp_path, "extras", [hit])  # e.g. extras saved earlier for a narrower window
    adapter = EntscheidsucheAdapter(snapshot_dir=tmp_path)
    records = list(adapter.parse(WINDOW, EXTRAS))
    assert [r.raw_file for r in records] == ["entscheidsuche/2025-12/page_001.json"]
    assert adapter.repeated_ids == [{"source_key": hit["_id"], "raw_file": "entscheidsuche/extras/page_001.json"}]


def test_official_url_only_when_the_record_carries_a_bger_url(tmp_path):
    hit = copy.deepcopy(next(h for h in fixture_hits() if h["_source"]["reference"] == [IN_WINDOW_GOLD]))
    url = (
        "https://www.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?highlight_docid=aza://11-12-2025-8C_72-2025"
    )
    hit["_source"]["attachment"]["source"] = url
    write_page(tmp_path, "2025-12", [hit])
    (record,) = EntscheidsucheAdapter(snapshot_dir=tmp_path).parse(WINDOW)
    assert record.fields["official_url"] == url


def test_parse_without_a_snapshot_yields_nothing(tmp_path):
    assert list(EntscheidsucheAdapter(snapshot_dir=tmp_path).parse(WINDOW)) == []


# ---------------------------------------------------------------------------------------- truncated texts

GOLD_ID = "CH_BGer_008_8C-72-2025_2025-12-11"
GOLD_HTML = (FIXTURE_ROOT / "html_samples" / f"{GOLD_ID}.html").read_bytes()
GOLD_URL = f"https://entscheidsuche.ch/docs/CH_BGer/{GOLD_ID}.html"
DECEMBER = Window("2025-12-01", "2025-12-31")


class FakeSite:
    """The search endpoint (FakeES) plus the per-ruling files: GET url -> bytes, or an HTTP status."""

    def __init__(self, hits, documents):
        self.search = FakeES(hits)
        self.documents = documents
        self.gets: list[str] = []

    def __call__(self, url, body, headers, timeout):
        if body is not None:
            return self.search(url, body, headers, timeout)
        assert headers["User-Agent"] == config.USER_AGENT and "Content-Type" not in headers
        self.gets.append(url)
        answer = self.documents.get(url, 404)
        return (answer, b"<html>not found</html>") if isinstance(answer, int) else (200, answer)


def hits_with_truncated_gold(keep_chars=3000):
    """The fixture hits, with 8C_72/2025 cut the way the search API cuts long rulings."""
    hits = fixture_hits()
    gold = next(h for h in hits if h["_id"] == GOLD_ID)
    gold["_source"]["attachment"]["content"] = gold["_source"]["attachment"]["content"][:keep_chars]
    gold["_source"]["attachment"]["content_length"] = es.API_CONTENT_LIMIT
    return hits


def test_html_to_text_strips_tags_scripts_and_entities():
    raw = (
        b"<html><head><title>T</title><style>p{color:red}</style><script>var "
        b"a='<p>x</p>';</script></head><body><p>Art.&nbsp;8 <a href='#'>ATSG</a>&amp; "
        b"Co</p><div>Zeile<br>zwei</div><table><tr><td>A</td><td>B</td></tr></table>f&uuml;r</body></html>"
    )
    text = es.html_to_text(raw)
    assert textnorm.normalise(text) == "T Art.\xa08 ATSG& Co Zeile zwei A B für".replace("\xa0", " ")
    assert "\xa0" in text and "color" not in text and "var a" not in text
    assert es.html_to_text(raw) == text
    assert es.html_to_text("Gerichtsschreiberin: M\xfcller".encode("cp1252")) == "Gerichtsschreiberin: Müller"


def test_html_extraction_of_a_real_document_equals_the_api_text():
    api_text = next(h for h in fixture_hits() if h["_id"] == GOLD_ID)["_source"]["attachment"]["content"]
    extracted = es.html_to_text(GOLD_HTML)
    assert textnorm.compare_key(extracted) == textnorm.compare_key(api_text)
    assert textnorm.text_hash(extracted) == textnorm.text_hash(api_text)
    assert textnorm.bad_text_reason(extracted) is None


def test_is_truncated_and_document_url():
    source = hits_with_truncated_gold()[0]["_source"]
    assert not es.is_truncated(source)
    by_length = {"attachment": {"content": "x" * 5000, "content_length": 100000}}
    by_text = {"attachment": {"content": "x" * 99992, "content_length": 123456}}
    assert es.is_truncated(by_length) and es.is_truncated(by_text)
    assert not es.is_truncated({"attachment": {"content": "x" * 5000, "content_length": 5008}})
    assert es.document_url(GOLD_ID, {"attachment": {"content_url": GOLD_URL}}) == GOLD_URL
    for elsewhere in ("https://www.bger.ch/x.html", "https://entscheidsuche.ch/other/x.html", None):
        assert es.document_url(GOLD_ID, {"attachment": {"content_url": elsewhere}}) == GOLD_URL


def test_truncated_hit_triggers_a_document_download(tmp_path):
    site = FakeSite(hits_with_truncated_gold(), {GOLD_URL: GOLD_HTML})
    adapter = make_adapter(tmp_path, site)
    written = adapter.fetch(DECEMBER)
    assert written == [
        "entscheidsuche/2025-12/page_001.json",
        "entscheidsuche/2025-12/page_002.json",
        f"entscheidsuche/documents/{GOLD_ID}.html",
    ]
    assert site.gets == [GOLD_URL]  # only the truncated hit, and after the pages
    assert (tmp_path / written[-1]).read_bytes() == GOLD_HTML  # raw bytes, unchanged
    assert adapter.documents_needed == 1 and adapter.documents_missing == []
    assert adapter.request_count == 3
    assert not list(tmp_path.rglob("*.tmp"))


def test_no_document_is_downloaded_when_nothing_is_truncated(tmp_path):
    site = FakeSite(fixture_hits(), {})
    assert all("documents" not in w for w in make_adapter(tmp_path, site).fetch(WINDOW, EXTRAS))
    assert site.gets == [] and not (tmp_path / "entscheidsuche/documents").exists()


def test_existing_document_is_not_downloaded_again(tmp_path):
    make_adapter(tmp_path, FakeSite(hits_with_truncated_gold(), {GOLD_URL: GOLD_HTML})).fetch(DECEMBER)
    before = tree_bytes(tmp_path)

    site = FakeSite(hits_with_truncated_gold(), {GOLD_URL: b"<html>a different answer</html>"})
    again = make_adapter(tmp_path, site)
    assert again.fetch(DECEMBER) == []
    assert site.gets == [] and site.search.calls == [] and again.request_count == 0
    assert tree_bytes(tmp_path) == before and again.documents_needed == 1


def test_a_missing_document_is_recorded_and_does_not_fail_the_fetch(tmp_path):
    hits = hits_with_truncated_gold()
    other = next(h for h in hits if h["_id"] == "CH_BGer_009_9C-467-2025_2025-12-16")
    other["_source"]["attachment"]["content_length"] = es.API_CONTENT_LIMIT
    other_url = other["_source"]["attachment"]["content_url"]
    site = FakeSite(hits, {other_url: b"<html><body><p>Urteil</p></body></html>"})  # the gold document answers 404
    adapter = make_adapter(tmp_path, site)
    written = adapter.fetch(DECEMBER)

    assert site.gets == [GOLD_URL, other_url]  # sorted by _id, and the 404 did not stop the second one
    assert written[-1] == f"entscheidsuche/documents/{other['_id']}.html" and len(written) == 3
    assert adapter.documents_missing == [{"source_key": GOLD_ID, "url": GOLD_URL, "status": 404}]
    assert adapter.documents_needed == 2
    assert not (tmp_path / f"entscheidsuche/documents/{GOLD_ID}.html").exists()

    # parse falls back to the (truncated) API text for the ruling without a document
    record = next(r for r in adapter.parse(DECEMBER) if r.source_key == GOLD_ID)
    assert record.record["text_origin"] == "search_api" and len(record.text) == 3000

    # a later fetch asks again for the missing one only
    retry = FakeSite(hits, {GOLD_URL: GOLD_HTML})
    assert make_adapter(tmp_path, retry).fetch(DECEMBER) == [f"entscheidsuche/documents/{GOLD_ID}.html"]
    assert retry.gets == [GOLD_URL]


def test_refusal_while_downloading_documents_raises(tmp_path):
    site = FakeSite(hits_with_truncated_gold(), {GOLD_URL: 403})
    with pytest.raises(EntscheidsucheRefused, match="403"):
        make_adapter(tmp_path, site).fetch(DECEMBER)
    assert not (tmp_path / "entscheidsuche/documents").exists()
    assert len(tree_bytes(tmp_path)) == 2  # the complete month pages stay


def test_parse_prefers_the_document_text(tmp_path):
    adapter = make_adapter(tmp_path, FakeSite(hits_with_truncated_gold(), {GOLD_URL: GOLD_HTML}))
    adapter.fetch(DECEMBER)
    records = list(adapter.parse(DECEMBER))
    assert len(records) == 5 and adapter.bad_documents == []

    gold = next(r for r in records if r.source_key == GOLD_ID)
    assert gold.text == es.html_to_text(GOLD_HTML)
    assert textnorm.bad_text_reason(gold.text) is None
    full_api_text = next(h for h in fixture_hits() if h["_id"] == GOLD_ID)["_source"]["attachment"]["content"]
    assert textnorm.text_hash(gold.text) == textnorm.text_hash(full_api_text)
    assert gold.record["text_origin"] == "document_html"
    assert gold.record["api_content_length"] == 3000
    assert gold.record["document_file"] == f"entscheidsuche/documents/{GOLD_ID}.html"
    assert gold.raw_file.startswith("entscheidsuche/2025-12/page_00")  # still the page file
    assert "content" not in gold.record["attachment"]
    assert gold.docket == IN_WINDOW_GOLD and gold.fields == {"language": "fr", "division": "8C"}

    others = [r for r in records if r.source_key != GOLD_ID]
    assert all(r.record["text_origin"] == "search_api" for r in others)
    assert all("document_file" not in r.record and "api_content_length" not in r.record for r in others)

    assert list(adapter.parse(DECEMBER)) == records  # deterministic
    assert list(EntscheidsucheAdapter(snapshot_dir=tmp_path).parse(DECEMBER)) == records


def test_a_document_that_is_still_bad_is_kept_and_listed(tmp_path):
    stub = b"<html><body><p>Seite nicht vorhanden</p></body></html>"
    adapter = make_adapter(tmp_path, FakeSite(hits_with_truncated_gold(), {GOLD_URL: stub}))
    adapter.fetch(DECEMBER)
    gold = next(r for r in adapter.parse(DECEMBER) if r.source_key == GOLD_ID)
    assert gold.text == "\n\n\nSeite nicht vorhanden\n\n\n" and gold.record["text_origin"] == "document_html"
    assert adapter.bad_documents == [
        {"source_key": GOLD_ID, "docket": IN_WINDOW_GOLD, "reason": "too_short",
         "document_file": f"entscheidsuche/documents/{GOLD_ID}.html"}
    ]  # fmt: skip


def test_fixture_records_come_from_the_search_api():
    _, records = parse_fixtures()
    assert {r.record["text_origin"] for r in records} == {"search_api"}

"""Swiss Case Law adapter. Offline: real rows in tests/fixtures/swiss_caselaw/, no network, no database."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from suva_data import config, textnorm
from suva_data.config import Window
from suva_data.models import SourceAdapter, SourceRecord
from suva_data.sources import swiss_caselaw as sc

FIXTURES = Path(__file__).parent / "fixtures" / "swiss_caselaw"
WINDOW = config.DEFAULT_WINDOW
EXTRA = frozenset({"8C_176/2025"})  # decided 2025-09-19, before the window
WINDOW_IDS = [
    "bger_12T_2_2025",
    "bger_1C_359_2025",
    "bger_1C_359_2025-D20251201",
    "bger_7B_1356_2025",
    "bger_7B_1356_2025-D20260318",
    "bger_7B_763_2025",
    "bger_8C_72_2025",
]
STATUTE_COLUMNS = ["decision_id", "law_code", "article", "paragraph", "mention_count"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any download attempt fails the test, unless the test installs its own fake."""

    def refuse(*args, **kwargs):
        raise AssertionError("fetch tried to download although the originals are present")

    monkeypatch.setattr(sc, "hf_hub_download", refuse)


@pytest.fixture
def adapter(tmp_path, monkeypatch) -> sc.SwissCaselawAdapter:
    """Fixture originals laid out like RAW_DIR, pinned to their own sha256."""
    adapter = sc.SwissCaselawAdapter(raw_dir=tmp_path / "raw", snapshot_dir=tmp_path / "snapshot")
    for repo_file in config.SWISS_CASELAW_FILES:
        target = adapter.raw_path(repo_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / repo_file, target)
    monkeypatch.setattr(config, "SWISS_CASELAW_FILES", {f: sha256(FIXTURES / f) for f in config.SWISS_CASELAW_FILES})
    return adapter


def records(adapter, window=WINDOW, extra=frozenset()) -> dict[str, SourceRecord]:
    out = list(adapter.parse(window, extra))
    assert [r.source_key for r in out] == sorted(r.source_key for r in out)
    return {r.source_key: r for r in out}


# --- fetch ------------------------------------------------------------------------------------------


def test_fixture_is_small():
    assert sum(f.stat().st_size for f in FIXTURES.rglob("*.parquet")) < 300_000


def test_adapter_satisfies_the_contract(adapter):
    candidate: SourceAdapter = adapter
    assert candidate.name == config.SWISS_CASELAW == "swiss_caselaw"


def test_fetch_writes_window_rows_sorted_with_all_columns(adapter):
    written = adapter.fetch(WINDOW)
    assert written == ["swiss_caselaw/bger_window.parquet", "swiss_caselaw/statute_references_window.parquet"]
    subset = pq.read_table(adapter.snapshot_dir / written[0])
    original = pq.read_table(FIXTURES / "data/bger.parquet")
    assert subset.column("decision_id").to_pylist() == WINDOW_IDS  # the 2025-09-19 row is excluded
    assert subset.schema.names == original.schema.names
    assert subset.schema.metadata is None
    by_id = {r["decision_id"]: r for r in original.to_pylist()}
    assert subset.to_pylist() == [by_id[i] for i in WINDOW_IDS]  # every value untouched, text included
    assert adapter.fetch_stats["rows_scanned"] == 8
    assert adapter.fetch_stats["rows_written"] == adapter.fetch_stats["rows_in_window"] == 7


def test_fetch_adds_extra_dockets_outside_the_window(adapter):
    adapter.fetch(WINDOW, EXTRA)
    ids = pq.read_table(adapter.bger_snapshot, columns=["decision_id"]).column(0).to_pylist()
    assert ids == sorted(WINDOW_IDS + ["bger_8C_176_2025"])
    assert adapter.fetch_stats["rows_extra_only"] == 1


def test_fetch_respects_the_window_argument(adapter):
    adapter.fetch(Window("2026-03-01", "2026-03-31"))
    ids = pq.read_table(adapter.bger_snapshot, columns=["decision_id"]).column(0).to_pylist()
    assert ids == ["bger_7B_1356_2025-D20260318"]


def test_fetch_is_byte_identical_when_repeated(adapter, tmp_path):
    adapter.fetch(WINDOW, EXTRA)
    first = {p: sha256(p) for p in (adapter.bger_snapshot, adapter.statutes_snapshot)}
    adapter.fetch(WINDOW, EXTRA)
    assert {p: sha256(p) for p in first} == first
    # ... and independent of the directory and of the cached checksum marker
    other = sc.SwissCaselawAdapter(raw_dir=adapter.raw_dir, snapshot_dir=tmp_path / "elsewhere")
    other.fetch(WINDOW, EXTRA)
    assert sha256(other.bger_snapshot) == first[adapter.bger_snapshot]
    assert sha256(other.statutes_snapshot) == first[adapter.statutes_snapshot]
    assert not list(adapter.bger_snapshot.parent.glob("*.tmp"))


def test_fetch_statute_refs_only_for_decisions_in_the_subset(adapter):
    adapter.fetch(WINDOW)
    refs = pq.read_table(adapter.statutes_snapshot)
    assert refs.schema.names == STATUTE_COLUMNS
    rows = refs.to_pylist()
    ids = {r["decision_id"] for r in rows}
    assert ids <= set(WINDOW_IDS)
    assert "bger_8C_72_2025" in ids
    assert not ids & {"bger_8C_129_2025", "bger_4A_106_2025", "bger_8C_176_2025"}  # present in the fixture original
    original = [
        r
        for r in pq.read_table(FIXTURES / "graph/statute_references.parquet").to_pylist()
        if r["decision_id"] in WINDOW_IDS
    ]
    key = lambda r: tuple((r[c] is None, r[c]) for c in STATUTE_COLUMNS)  # noqa: E731  (nulls last)
    assert rows == sorted(original, key=key)

    adapter.fetch(WINDOW, EXTRA)
    assert "bger_8C_176_2025" in set(pq.read_table(adapter.statutes_snapshot).column("decision_id").to_pylist())


def test_fetch_raises_on_sha256_mismatch(adapter, monkeypatch):
    pinned = dict(config.SWISS_CASELAW_FILES)
    monkeypatch.setattr(config, "SWISS_CASELAW_FILES", pinned | {"data/bger.parquet": "0" * 64})
    with pytest.raises(sc.ChecksumMismatch, match="bger.parquet.*expected 0000"):
        adapter.fetch(WINDOW)
    assert not adapter.bger_snapshot.exists()


def test_fetch_detects_a_file_changed_after_verification(adapter):
    adapter.fetch(WINDOW)
    with adapter.raw_path("graph/statute_references.parquet").open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(sc.ChecksumMismatch, match="statute_references.parquet"):
        adapter.fetch(WINDOW)


def test_checksum_is_cached_until_the_file_changes(adapter, monkeypatch):
    calls = []
    real = sc._sha256
    monkeypatch.setattr(sc, "_sha256", lambda path: calls.append(path.name) or real(path))
    adapter.fetch(WINDOW)
    assert sorted(calls) == ["bger.parquet", "statute_references.parquet"]
    adapter.fetch(WINDOW)
    assert len(calls) == 2  # not hashed again


def test_fetch_downloads_only_missing_files_at_the_pinned_revision(adapter, monkeypatch):
    adapter.raw_path("graph/statute_references.parquet").unlink()
    calls = []

    def fake_download(repo_id, filename, repo_type, revision, local_dir):
        calls.append((repo_id, filename, repo_type, revision))
        target = Path(local_dir) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / filename, target)
        return str(target)

    monkeypatch.setattr(sc, "hf_hub_download", fake_download)
    adapter.fetch(WINDOW)
    assert calls == [
        (config.SWISS_CASELAW_REPO, "graph/statute_references.parquet", "dataset", config.SWISS_CASELAW_REVISION)
    ]
    assert adapter.raw_path("graph/statute_references.parquet").exists()
    assert adapter.statutes_snapshot.exists()
    assert not (adapter.revision_dir / ".download").exists()


# --- parse ------------------------------------------------------------------------------------------


def test_parse_maps_a_ruling(adapter):
    adapter.fetch(WINDOW)
    r = records(adapter)["bger_8C_72_2025"]
    assert (r.source, r.docket, r.decision_date) == ("swiss_caselaw", "8C_72/2025", "2025-12-11")
    assert r.raw_file == "swiss_caselaw/bger_window.parquet"
    assert r.fields == {
        "language": "fr",
        "division": "8C",
        "area": "Assurance-accidents",
        "subject": "Assurance-accidents (rente d'invalidité; indemnité pour atteinte à l'intégrité)",
        "outcome": "dismissed",
        "cited_decisions": r.fields["cited_decisions"],
        "official_url": "http://relevancy.bger.ch/cgi-bin/JumpCGI?id=11.12.2025_8C_72/2025",
    }
    assert set(r.fields) <= set(config.CANONICAL_FIELDS)
    assert len(r.fields["cited_decisions"]) == 16
    assert r.fields["cited_decisions"][:2] == ["8C_196/2016", "8C_208/2016"]
    assert all(isinstance(c, str) for c in r.fields["cited_decisions"])


def test_parse_keeps_the_source_record_without_the_text(adapter):
    adapter.fetch(WINDOW)
    r = records(adapter)["bger_8C_72_2025"]
    columns = pq.read_schema(FIXTURES / "data/bger.parquet").names
    assert list(r.record) == [c for c in columns if c != "full_text"]
    assert r.record["chamber"] == "IV. Öffentlich-rechtliche Abteilung"
    assert r.record["title"].endswith(",")  # the record is the source's own value, uncleaned
    assert r.record["text_length"] == 22901 and type(r.record["text_length"]) is int
    assert r.record["has_full_text"] is True
    assert r.record["judges"] is None and r.record["publication_date"] is None
    assert json.loads(json.dumps(r.record, allow_nan=False)) == r.record


def test_parse_text_is_exactly_the_stored_text(adapter):
    adapter.fetch(WINDOW, EXTRA)
    stored = {r["decision_id"]: r["full_text"] for r in pq.read_table(FIXTURES / "data/bger.parquet").to_pylist()}
    parsed = records(adapter, extra=EXTRA)
    assert {k: r.text for k, r in parsed.items()} == stored
    assert len(parsed["bger_8C_72_2025"].text) == 22901


def test_parse_omits_unknown_values_instead_of_defaulting(adapter):
    adapter.fetch(WINDOW)
    parsed = records(adapter)
    for r in parsed.values():
        assert all(v is not None and v != "" and v != [] for v in r.fields.values()), r.source_key
    # 8C_72/2025: the dataset knows neither the publication date nor the star
    assert not {"publication_date", "starred"} & set(parsed["bger_8C_72_2025"].fields)
    # the error-page row: no title, area, outcome; cited_decisions is '[]'
    assert parsed["bger_7B_763_2025"].fields == {
        "language": "de",
        "division": "7B",
        "publication_date": "2026-07-10",
        "starred": False,  # a real value in the source, kept as a candidate (config.NEVER_CANONICAL)
        "official_url": parsed["bger_7B_763_2025"].record["source_url"],
    }


def test_parse_does_not_drop_duplicates_or_bad_texts(adapter):
    adapter.fetch(WINDOW)
    parsed = records(adapter)
    assert list(parsed) == WINDOW_IDS
    assert adapter.parse_stats == {"rows_read": 7, "records": 7, "not_selected": 0, "unparsable_docket": 0}

    a, twin = parsed["bger_1C_359_2025"], parsed["bger_1C_359_2025-D20251201"]  # exact duplicate
    assert (a.docket, a.decision_date) == (twin.docket, twin.decision_date) == ("1C_359/2025", "2025-12-01")
    assert a.text == twin.text
    assert a.fields["publication_date"] == "2025-12-01" and "publication_date" not in twin.fields

    first, second = parsed["bger_7B_1356_2025"], parsed["bger_7B_1356_2025-D20260318"]  # two real rulings
    assert first.docket == second.docket == "7B_1356/2025"
    assert (first.decision_date, second.decision_date) == ("2026-01-26", "2026-03-18")
    assert textnorm.text_hash(first.text) != textnorm.text_hash(second.text)

    assert textnorm.bad_text_reason(parsed["bger_7B_763_2025"].text) == "error_page"
    assert [k for k, r in parsed.items() if textnorm.bad_text_reason(r.text)] == ["bger_7B_763_2025"]


def test_parse_two_digit_division(adapter):
    adapter.fetch(WINDOW)
    r = records(adapter)["bger_12T_2_2025"]
    assert (r.docket, r.fields["division"]) == ("12T_2/2025", "12T")
    assert "outcome" not in r.fields
    assert r.fields["subject"] == "Aufsichtsanzeige nach Art. 1 Abs. 2 BGG in Verbindung mit Art. 71 VwVG"


def test_parse_selects_by_window_or_extra_docket(adapter):
    adapter.fetch(WINDOW, EXTRA)
    assert "bger_8C_176_2025" not in records(adapter)
    assert adapter.parse_stats["not_selected"] == 1
    extra = records(adapter, extra=EXTRA)["bger_8C_176_2025"]
    assert (extra.docket, extra.decision_date) == ("8C_176/2025", "2025-09-19")
    assert list(records(adapter, window=Window("2026-03-01", "2026-03-31"))) == ["bger_7B_1356_2025-D20260318"]


def test_parse_is_offline_and_reads_only_the_snapshot(adapter):
    adapter.fetch(WINDOW)
    shutil.rmtree(adapter.raw_dir)
    assert len(records(adapter)) == 7
    assert len(list(adapter.parse_statute_refs())) > 0


def test_parse_statute_refs(adapter):
    adapter.fetch(WINDOW)
    refs = list(adapter.parse_statute_refs())
    assert all(list(r) == STATUTE_COLUMNS for r in refs)
    assert {r["decision_id"] for r in refs} <= set(WINDOW_IDS)
    assert [r["decision_id"] for r in refs] == sorted(r["decision_id"] for r in refs)
    mine = [r for r in refs if r["decision_id"] == "bger_8C_72_2025"]
    assert len(mine) == 7
    assert all(isinstance(r["law_code"], str) and type(r["mention_count"]) is int for r in mine)
    assert any(r["paragraph"] is None for r in refs)  # null stays None
    json.dumps(refs, allow_nan=False)


def test_parse_handles_blank_values_and_unparsable_dockets(tmp_path):
    """Synthetic rows for cases the real window does not contain."""
    base = pq.read_table(FIXTURES / "data/bger.parquet").to_pylist()[0]

    def row(decision_id, **changes):
        unknown = dict.fromkeys(
            ("title", "legal_area", "outcome", "publication_date", "marked_for_publication", "cited_decisions")
        )
        return (
            base
            | unknown
            | {"decision_id": decision_id, "decision_date": "2025-11-03", "docket_number": "8C_1/2025"}
            | changes
        )

    rows = [
        row(
            "a_blank",
            title=" , ",
            legal_area="",
            outcome="  ",
            publication_date="",
            cited_decisions="",
            marked_for_publication=None,
        ),
        row(
            "b_filled",
            title="Rente ,  ",
            publication_date="2025-11-20T00:00:00",
            cited_decisions='["8C_2/2020", "", 7]',
            marked_for_publication=True,
        ),
        row("c_bad_json", cited_decisions="{not json", publication_date="20.11.2025"),
        row("d_no_docket", docket_number="BGE 150 V 1"),
        row("e_old_format", docket_number=" 8c-12-2025 ".upper()),
    ]
    adapter = sc.SwissCaselawAdapter(raw_dir=tmp_path / "raw", snapshot_dir=tmp_path / "snapshot")
    adapter.bger_snapshot.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=pq.read_schema(FIXTURES / "data/bger.parquet")), adapter.bger_snapshot
    )

    parsed = records(adapter)
    assert list(parsed) == ["a_blank", "b_filled", "c_bad_json", "e_old_format"]
    core = {"language": base["language"], "division": "8C", "official_url": base["source_url"]}
    assert parsed["a_blank"].fields == core
    assert parsed["b_filled"].fields == core | {
        "subject": "Rente",
        "publication_date": "2025-11-20",
        "starred": True,
        "cited_decisions": ["8C_2/2020"],
    }
    assert parsed["c_bad_json"].fields == core
    assert parsed["c_bad_json"].record["cited_decisions"] == "{not json"  # the raw value is still in the record
    assert parsed["e_old_format"].docket == "8C_12/2025"
    # the row without a BGer case number is reported, not silently dropped
    assert adapter.unparsable_dockets == [
        {"source_key": "d_no_docket", "docket_number": "BGE 150 V 1", "decision_date": "2025-11-03"}
    ]
    assert adapter.parse_stats == {"rows_read": 5, "records": 4, "not_selected": 0, "unparsable_docket": 1}


def test_parse_rejects_an_unsorted_snapshot(tmp_path):
    adapter = sc.SwissCaselawAdapter(raw_dir=tmp_path / "raw", snapshot_dir=tmp_path / "snapshot")
    adapter.bger_snapshot.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "data/bger.parquet", adapter.bger_snapshot)  # the fixture original is not sorted
    with pytest.raises(ValueError, match="not strictly sorted"):
        list(adapter.parse(WINDOW))


def test_jsonable_converts_nan_and_foreign_scalars():
    class Scalar:  # stands in for a numpy scalar
        def item(self):
            return 3

    assert sc._jsonable({"a": float("nan"), "b": [Scalar(), 1.5], "c": b"x"}) == {"a": None, "b": [3, 1.5], "c": "x"}

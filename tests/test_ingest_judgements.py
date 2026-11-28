"""Reading judgements/ without its personal fields (D-051): columns A and B, and the export links only."""

from __future__ import annotations

import re

import pytest

from src.ingest import judgements as jd


def test_list_rows_read_quarter_and_entry_only():
    rows = jd.list_rows()
    assert len(rows) == 60
    assert all(re.match(r"^\d{4} Q[1-4]$", r.quarter_label) for r in rows)
    joined = " ".join(r.entry for r in rows)
    assert "SharePoint" not in joined and "http" not in joined  # column D never read


def test_exports_give_docket_and_decision_date_from_the_link():
    refs = jd.export_refs()
    assert len(refs) == 55
    assert all(jd.DOCKET.match(r.docket) for r in refs)
    assert {r.docket for r in refs if r.file.endswith("Export_8C_176_2025 3.html")} == {"8C_176/2025"}


def test_entries_resolve_to_dockets_or_the_cantonal_title():
    exports = {r.docket for r in jd.export_refs()}
    assert jd.resolve_entry("8C_464/2025", exports) == ("8C_464/2025", None)
    assert jd.resolve_entry("BGer-Urteil 458/2025 vom 18. November 2025", exports) == ("8C_458/2025", None)
    title = "Entscheid des Kantonsgerichts Basel-Landschaft vom 5. Februar 2026"
    assert jd.resolve_entry(title, exports) == (None, title)
    with pytest.raises(ValueError, match="cannot resolve"):
        jd.resolve_entry("BGer-Urteil 999999/2025 vom 1. Januar 2026", exports)
    resolved = [jd.resolve_entry(r.entry, exports) for r in jd.list_rows()]
    assert sum(1 for docket, _ in resolved if docket) == 59
    assert sum(1 for _, title in resolved if title) == 1

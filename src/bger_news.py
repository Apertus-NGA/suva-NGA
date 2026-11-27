"""Compatibility shim: the crawler now lives in suva_data.sources.bger_lists (docs/ARCHITECTURE.md 3.3).

Kept so existing notebooks that import `bger_news` keep working. New code should use BgerListAdapter.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import date

from suva_data import config
from suva_data.sources.bger_lists import DEFAULT_DELAY_S, BlockedError, Entry, _weekdays, fetch_day, parse_day  # noqa: F401

CACHE = config.SNAPSHOT_DIR / config.BGER_LIST


def crawl(start: date, end: date) -> list[dict]:
    """Entries of all weekday lists from start to end; fetches missing days and stops at a firewall block."""
    rows: list[dict] = []
    for d in _weekdays(start, end):
        try:
            page, fetched = fetch_day(d, CACHE)
        except BlockedError:
            break
        if fetched:
            time.sleep(DEFAULT_DELAY_S)
        list_date, entries = parse_day(page)
        if list_date == d.isoformat():
            rows.extend(asdict(e) for e in entries)
    return rows

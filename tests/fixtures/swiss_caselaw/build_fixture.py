"""Rebuilds the fixture from the real snapshot (run `fetch` first). Not a test; run by hand:

    uv run python tests/fixtures/swiss_caselaw/build_fixture.py

Real rows, laid out like the Hugging Face repo: data/bger.parquet, graph/statute_references.parquet.
"""

from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from suva_data import config

HERE = Path(__file__).parent
SNAPSHOT = config.SNAPSHOT_DIR / config.SWISS_CASELAW
IDS = [
    "bger_8C_72_2025",  # the ruling verified by hand in DATA_LAYER 3.4
    "bger_1C_359_2025",  # exact duplicate pair ...
    "bger_1C_359_2025-D20251201",  # ... its "-D" twin
    "bger_7B_1356_2025",  # two real rulings on one case number ...
    "bger_7B_1356_2025-D20260318",  # ... the second one
    "bger_7B_763_2025",  # error page instead of the ruling
    "bger_12T_2_2025",  # two-digit division (administrative matter)
    "bger_8C_176_2025",  # decided 2025-09-19: outside the default window, a gold-summary extra
]
FOREIGN_STATUTE_IDS = ["bger_8C_129_2025", "bger_4A_106_2025"]  # decisions NOT in bger.parquet

rulings = pq.read_table(SNAPSHOT / "bger_window.parquet", filters=pc.field("decision_id").isin(IDS))
assert rulings.num_rows == len(IDS), rulings.num_rows
# Deliberately not sorted by decision_id, so the adapter's sort is exercised.
rulings = rulings.sort_by([("text_length", "ascending"), ("decision_id", "ascending")])
(HERE / "data").mkdir(exist_ok=True)
pq.write_table(rulings, HERE / "data" / "bger.parquet", compression="zstd", compression_level=19, row_group_size=3)

statutes = pq.read_table(
    SNAPSHOT / "statute_references_window.parquet", filters=pc.field("decision_id").isin(IDS + FOREIGN_STATUTE_IDS)
)
statutes = statutes.sort_by([("mention_count", "descending"), ("article", "ascending"), ("decision_id", "ascending")])
(HERE / "graph").mkdir(exist_ok=True)
pq.write_table(statutes, HERE / "graph" / "statute_references.parquet", compression="zstd", row_group_size=40)
print(rulings.num_rows, "rulings,", statutes.num_rows, "statute rows")

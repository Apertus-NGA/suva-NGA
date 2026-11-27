"""Single place for paths, the decision-date window, pinned versions and the hierarchy of truth.

Nothing else in the package may hard-code these values (docs/ARCHITECTURE.md, sections 2, 4, 11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JUDGEMENTS_DIR = REPO / "judgements"
LABELS_XLSX = JUDGEMENTS_DIR / "BG_Urteile_2025_Q4_2026_Q1.xlsx"
MIGRATIONS_DIR = REPO / "db" / "migrations"
CERT_INTERMEDIATE = REPO / "src" / "certs" / "digicert_global_g2_tls_rsa_sha256_2020_ca1.pem"

DATA_DIR = Path(os.environ.get("SUVA_DATA_DIR", REPO / "data"))
RAW_DIR = DATA_DIR / "raw"  # fetch cache; may hold large originals; never published
SNAPSHOT_DIR = DATA_DIR / "snapshot"  # the published raw inputs; everything after `fetch` reads only from here
DUMP_DIR = DATA_DIR / "dump"
MANIFEST_PATH = DATA_DIR / "manifest.json"  # committed
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.md"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:suva@localhost:54329/suva")

# --- sources, in order of trust (tier 1 = ground truth) ---------------------------------------
BGER_LIST = "bger_list"  # bger.ch daily "Neue Entscheide" lists
BGER_RULING = "bger_ruling"  # bger.ch ruling pages (single rulings only)
ENTSCHEIDSUCHE = "entscheidsuche"
SWISS_CASELAW = "swiss_caselaw"
SOURCE_TIER = {BGER_LIST: 1, BGER_RULING: 1, ENTSCHEIDSUCHE: 2, SWISS_CASELAW: 3}

# Fields a source may propose for the canonical `rulings` row.
CANONICAL_FIELDS = (
    "language",  # 'de' | 'fr' | 'it'
    "division",  # docket prefix, e.g. '8C'
    "publication_date",  # ISO date
    "starred",  # bool: marked for publication (BGE candidate)
    "area",  # Sachgebiet
    "subject",  # subject line / Gegenstand
    "outcome",  # derived (third party)
    "cited_decisions",  # list[str], derived
    "official_url",
)
DERIVED_FIELDS = ("outcome", "cited_decisions")
# Sources whose value for a field must never become canonical (Phase 0: unreliable).
NEVER_CANONICAL = {(SWISS_CASELAW, "starred")}

# --- pinned inputs ------------------------------------------------------------------------------
SWISS_CASELAW_REPO = "voilaj/swiss-caselaw"
SWISS_CASELAW_REVISION = "35b17aa9c3fad71011b72f78f6ab79650ec0cf96"
SWISS_CASELAW_FILES = {
    "data/bger.parquet": "d2b2df1dedb05c62d91d834ddb6ba8084c31fae61a427fd4541a72ed35bb3711",
    "graph/statute_references.parquet": "8e929cdc289cc5f2b4e54067b8a374398b3a752724a55d6160eb63251b922b11",
}
# Where OUR snapshot + dump are published (public Hugging Face dataset; pinned by tag when released).
OWN_DATASET_REPO = "suva-nga/bger-rulings"
OWN_DATASET_REVISION = "7eb6025dcac351e426a0fcae1cba3a02c332e7ed"  # pinned upload; replace with the release tag (e.g. "v1.0") once tagged

ENTSCHEIDSUCHE_SEARCH_URL = "https://entscheidsuche.ch/_search.php"
USER_AGENT = "hackapertus-suva-data/0.1 (research; sequential; contact via repo)"


@dataclass(frozen=True)
class Window:
    """Rulings are selected by DECISION date (organiser, 2026-11-27)."""

    decision_from: str = "2025-10-01"
    decision_to: str = "2026-06-30"

    def contains(self, iso_date: str | None) -> bool:
        return bool(iso_date) and self.decision_from <= iso_date[:10] <= self.decision_to


DEFAULT_WINDOW = Window()
# Quarters with a complete relevance list: everything decided here and not labelled is "not relevant".
LABELLED_FROM, LABELLED_TO = "2025-10-01", "2026-03-31"
LABEL_SET_XLSX = "suva_xlsx_2025Q4_2026Q1"

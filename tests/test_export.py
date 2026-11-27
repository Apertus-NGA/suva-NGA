"""Parquet export: same database -> identical files, and the contents match the database."""

import pyarrow.parquet as pq
import pytest

from suva_data import config, export, load, reconcile as rec
from suva_data.models import SourceRecord

pytestmark = pytest.mark.db

SIG = " Im Namen des Schweizerischen Bundesgerichts. Die Präsidentin: X. Der Gerichtsschreiber: Y."
TEXT_A = "Urteil vom 11. Dezember 2025. " + "Erwägung. " * 100 + SIG
TEXT_B = "Arrêt du 15 novembre 2025. " + "Considérant. " * 100 + SIG


def R(source, key, docket, date, text=None, **fields):
    return SourceRecord(source=source, source_key=key, docket=docket, decision_date=date, fields=fields, record={"k": key}, text=text)


@pytest.fixture
def small_db(db_conn):
    load.load_source_records(db_conn, [
        R(config.BGER_LIST, "2026-01-14:8C_72/2025", "8C_72/2025", "2025-12-11", publication_date="2026-01-14", starred=True, area="Unfallversicherung"),
        R(config.ENTSCHEIDSUCHE, "es-a", "8C_72/2025", "2025-12-11", text=TEXT_A, language="de"),
        R(config.SWISS_CASELAW, "hf-a", "8C_72/2025", "2025-12-11", text=TEXT_A, language="de", outcome="dismissed", cited_decisions=["8C_1/2020", "BGE 134 V 109"]),
        R(config.SWISS_CASELAW, "hf-b", "9C_5/2025", "2025-11-15", text=TEXT_B, language="fr"),
        R(config.SWISS_CASELAW, "hf-c", "8C_9/2026", "2026-05-02", text=TEXT_A + " c", language="de"),
    ])
    rec.reconcile(db_conn)
    rid = db_conn.execute("SELECT id FROM rulings WHERE docket = '8C_72/2025'").fetchone()[0]
    db_conn.execute("INSERT INTO labels (ruling_id, label_set, value, quarter, metadata) VALUES (%s, %s, 'relevant', '2025 Q4', %s)",
                    (rid, config.LABEL_SET_XLSX, '{"xlsx_title": "8C_72/2025", "xlsx_row": 5, "erstellt": "2026-01-19T14:41:32"}'))
    for lang in ("de", "fr"):
        db_conn.execute("INSERT INTO gold_summaries (ruling_id, language, title, body, author) VALUES (%s, %s, 'Titel', 'Absatz 1\n\nAbsatz 2', 'A')", (rid, lang))
    return db_conn


def test_export_is_deterministic_and_complete(small_db, tmp_path):
    a = export.export_tables(small_db, tmp_path / "a")
    b = export.export_tables(small_db, tmp_path / "b")
    assert set(a) == {f"{t}.parquet" for t in export.TABLES} | {"schema.sql"}
    assert {k: v["sha256"] for k, v in a.items()} == {k: v["sha256"] for k, v in b.items()}  # byte-identical
    assert a["rulings.parquet"]["rows"] == 3 and a["gold_summaries.parquet"]["rows"] == 2 and a["labels.parquet"]["rows"] == 1
    assert a["ruling_texts.parquet"]["rows"] == 4 and a["source_records.parquet"]["rows"] == 5
    assert "CREATE TABLE rulings" in (tmp_path / "a" / "schema.sql").read_text()


def test_rulings_table_contents(small_db, tmp_path):
    export.export_tables(small_db, tmp_path)
    rows = {r["docket"]: r for r in pq.read_table(tmp_path / "rulings.parquet").to_pylist()}
    assert list(rows) == ["9C_5/2025", "8C_72/2025", "8C_9/2026"]  # ordered by decision date
    a = rows["8C_72/2025"]
    assert a["text"] == TEXT_A and a["text_source"] == config.ENTSCHEIDSUCHE and a["n_text_sources"] == 2
    assert a["relevance"] == "relevant" and a["relevance_basis"] == "suva_xlsx" and a["has_gold_summary"] is True
    assert a["starred"] is True and str(a["publication_date"]) == "2026-01-14" and a["decision_quarter"] == "2025 Q4"
    assert a["cited_decisions"] == ["8C_1/2020", "BGE 134 V 109"] and a["outcome"] == "dismissed"
    b, c = rows["9C_5/2025"], rows["8C_9/2026"]
    assert b["relevance"] == "not_relevant" and b["starred"] is None and b["publication_date"] is None  # unknown stays null
    assert c["relevance"] == "unknown" and c["has_gold_summary"] is False


def test_labels_and_texts_tables(small_db, tmp_path):
    export.export_tables(small_db, tmp_path)
    (label,) = pq.read_table(tmp_path / "labels.parquet").to_pylist()
    assert label["docket"] == "8C_72/2025" and label["xlsx_row"] == 5 and label["erstellt"] == "2026-01-19T14:41:32"
    texts = pq.read_table(tmp_path / "ruling_texts.parquet").to_pylist()
    assert sum(t["is_canonical"] for t in texts) == 3
    assert {t["source"] for t in texts if t["docket"] == "8C_72/2025"} == {config.ENTSCHEIDSUCHE, config.SWISS_CASELAW}


def test_export_of_an_empty_database_writes_valid_files(db_conn, tmp_path):
    out = export.export_tables(db_conn, tmp_path)
    assert out["rulings.parquet"]["rows"] == 0
    assert pq.read_table(tmp_path / "rulings.parquet").num_rows == 0

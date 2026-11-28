"""Gold-summary loader: parsing of the real exports (DATA_LAYER 3.2) and the database contract."""

from __future__ import annotations

import dataclasses
import re
import shutil
from collections import Counter

import pytest

from suva_data import config
from suva_data.loaders.gold_summaries import (
    GoldSummary,
    GoldSummaryError,
    parse_export,
    parse_title_date,
    read_gold_summaries,
    title_language,
    write_gold_summaries,
)
from suva_data.loaders.labels_xlsx import read_labels


@pytest.fixture(scope="module")
def real() -> list[GoldSummary]:
    return read_gold_summaries()


def export_html(de="<p>Eins.</p><p>Zwei.</p>", fr="<p>Un.</p>", title="BGer-Urteil 8C_1/2025 vom 4. Dezember 2025") -> str:
    de_section = f"<h2>Text DE</h2>{de}" if de is not None else ""
    fr_section = f"<h2>Text FR</h2>{fr}" if fr is not None else ""
    return (
        f'<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><title>{title}</title></head><body><hr>'
        f"<h1>{title}</h1>{de_section}{fr_section}"
        '<h2>Link zum Urteil</h2><p><a href="https://search.bger.ch/x?a=1&lang=de&amp;type=show_document">link</a></p>'
        "<h2>Autor</h2><p>Muster Anna (MUA), Rechtsanwältin</p><hr></body></html>"
    )


# --- pure parsing, real files -----------------------------------------------------------------------


def test_real_files_numbers(real):
    assert len(real) == 55
    assert len({s.docket for s in real}) == 55
    assert all(s.body_de.strip() and s.body_fr.strip() for s in real)
    # Three authors; the names themselves stay in judgements/ and are not repeated here (D-051).
    assert sorted(Counter(s.author for s in real).values()) == [3, 14, 38]
    assert Counter(s.title_language for s in real) == {"fr": 31, "de": 22, "it": 2}
    assert all(s.decision_date_from_title for s in real)
    assert all(s.source_url and s.source_url.startswith("http") for s in real)
    assert [s.source_file for s in real] == sorted(s.source_file for s in real)


def test_32_summaries_are_labelled_and_23_are_not(real):
    labelled = {row.docket for row in read_labels().rows}
    assert sum(s.docket in labelled for s in real) == 32
    assert sum(s.docket not in labelled for s in real) == 23


def test_docket_comes_from_the_filename_even_with_a_stray_suffix(real):
    (stray,) = [s for s in real if s.source_file == "Export_8C_176_2025 3.html"]
    assert stray.docket == "8C_176/2025"
    assert stray.title == "Arrêt du TF 8C_176/2025 du 19 septembre 2025"
    assert stray.decision_date_from_title == "2025-09-19"


def test_docket_comes_from_the_filename_when_the_title_has_none(real):
    (summary,) = [s for s in real if s.source_file == "Export_8C_458_2025.html"]
    assert summary.title == "BGer-Urteil 458/2025 vom 18. November 2025"
    assert summary.docket == "8C_458/2025"
    assert summary.decision_date_from_title == "2025-11-18"


def test_real_file_content(real):
    summary = next(s for s in real if s.docket == "8C_72/2025")
    assert summary.title == "Arrêt du TF 8C_72/2025 du 11 décembre 2025"
    assert summary.title_language == "fr"
    assert summary.decision_date_from_title == "2025-12-11"
    # Shape only ("Surname Given (CODE), title"): the value stays in judgements/ (D-051).
    assert re.fullmatch(r"\S+ \S+ \(\w{2,4}\), \S.*", summary.author)
    assert summary.author == Counter(s.author for s in real).most_common(1)[0][0]
    assert summary.source_url == (
        "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php"
        "?highlight_docid=aza://11-12-2025-8C_72-2025&lang=de&zoom=&type=show_document"
    )
    raw = (config.JUDGEMENTS_DIR / summary.source_file).read_text(encoding="utf-8")
    de_html, fr_html = raw.split("<h2>Text DE</h2>")[1].split("<h2>Text FR</h2>")
    fr_html = fr_html.split("<h2>Link zum Urteil</h2>")[0]
    assert len(summary.body_de.split("\n\n")) == de_html.count("<p>")
    assert len(summary.body_fr.split("\n\n")) == fr_html.count("<p>")
    assert "<" not in summary.body_de and "<" not in summary.body_fr


def test_every_real_paragraph_is_kept(real):
    # 431 <p> in the 55 files = 321 body paragraphs + 55 link + 55 author paragraphs
    assert sum(len(s.body_de.split("\n\n")) + len(s.body_fr.split("\n\n")) for s in real) == 321


def test_link_pasted_as_plain_text_is_still_the_source_url(real):
    summary = next(s for s in real if s.docket == "8C_275/2025")  # the only export without an <a href>
    assert summary.source_url == (
        "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php"
        "?highlight_docid=aza://01-12-2025-8C_275-2025&lang=de&zoom=&type=show_document"
    )


def test_title_date_matches_the_date_in_the_official_link(real):
    import re

    for s in real:
        day, month, year = re.search(r"aza://(\d\d)-(\d\d)-(\d{4})-", s.source_url).groups()
        assert s.decision_date_from_title == f"{year}-{month}-{day}", s.source_file


# --- pure parsing, small cases ----------------------------------------------------------------------


def test_paragraph_handling():
    html = export_html(
        de="<p>Erster   Absatz\n mit <b>fett</b> &amp; <i>kursiv</i>,<br>CHF&nbsp;80.&ndash; und &#167; 6.</p>\n"
        "<p>  </p><p></p><p>&nbsp;</p>\n<p>Zweiter\tAbsatz &lt;Art. 4 ATSG&gt;.</p>",
        fr="<p>Seul paragraphe&nbsp;: «&nbsp;oui&nbsp;».</p>",
    )
    summary = parse_export(html, "Export_8C_1_2025.html")
    assert summary.body_de == "Erster Absatz mit fett & kursiv, CHF\xa080.– und § 6.\n\nZweiter Absatz <Art. 4 ATSG>."
    assert summary.body_fr == "Seul paragraphe\xa0: «\xa0oui\xa0»."
    assert summary.author == "Muster Anna (MUA), Rechtsanwältin"
    assert summary.source_url == "https://search.bger.ch/x?a=1&lang=de&type=show_document"


def test_author_without_paragraph_tag_and_missing_link():
    html = (
        "<h1>Arrêt du TF 9C_2/2025 du 1er mars 2026</h1><h2>Text DE</h2><p>A</p><h2>Text FR</h2><p>B</p>"
        "<h2>Link zum Urteil</h2><h2>Autor</h2>\n Muster Anna (MUA),\n Rechtsanwältin\n"
    )
    summary = parse_export(html, "Export_9C_2_2025.html")
    assert summary.author == "Muster Anna (MUA), Rechtsanwältin"
    assert summary.source_url is None
    assert (summary.docket, summary.title_language, summary.decision_date_from_title) == ("9C_2/2025", "fr", "2026-03-01")


@pytest.mark.parametrize(
    ("title", "language", "date"),
    [
        ("BGer-Urteil 4A_106/2025 vom 4. August 2025", "de", "2025-08-04"),
        ("BGer-Urteil 8C_18/2026 vom 2. März 2026", "de", "2026-03-02"),
        ("BGer-Urteil 8C_366/2024 vom 23. Dezember 2025", "de", "2025-12-23"),
        ("Arrêt du TF 8C_330/2025 du 1er septembre 2025", "fr", "2025-09-01"),
        ("Arrêt du TC 8C_154/2025 du 11 août 2025", "fr", "2025-08-11"),
        ("Arrêt du TF 8C_314/2025 du 9 février 2026", "fr", "2026-02-09"),
        ("Arrêt du TF 8C_72/2025 du 11 décembre 2025", "fr", "2025-12-11"),
        ("Sentenza del TF 8C_135/2025 del 21 agosto 2025", "it", "2025-08-21"),
        ("Sentenza del TF 9C_65/2025 del 29 gennaio 2026, destinata alla pubblicazione negli DTF", "it", "2026-01-29"),
    ],
)
def test_title_language_and_month_names(title, language, date):
    assert title_language(title) == language
    assert parse_title_date(title) == date


@pytest.mark.parametrize(
    "title",
    ["BGer-Urteil 8C_1/2025", "BGer-Urteil 8C_1/2025 vom 4. Augst 2025", "BGer-Urteil 8C_1/2025 vom 31. Februar 2026", ""],
)
def test_unparseable_title_date_is_none(title):
    assert parse_title_date(title) is None


@pytest.mark.parametrize(
    ("html", "filename", "message"),
    [
        (export_html(de=None), "Export_8C_1_2025.html", "'Text DE' is missing"),
        (export_html(fr=None), "Export_8C_1_2025.html", "'Text FR' is missing"),
        (export_html(de="<p> </p><p>&nbsp;</p>"), "Export_8C_1_2025.html", "'Text DE' is empty"),
        (export_html(fr=""), "Export_8C_1_2025.html", "'Text FR' is empty"),
        (export_html(fr="Texte sans paragraphe"), "Export_8C_1_2025.html", "text outside <p>"),
        (export_html(), "Export_summary.html", "no Federal Supreme Court case number"),
        (export_html(), "Export_8C_2_2025.html", "file name says 8C_2/2025 but the title says 8C_1/2025"),
        (export_html(title="Urteil 8C_1/2025 vom 4. Dezember 2025"), "Export_8C_1_2025.html", "language"),
    ],
)
def test_broken_files_fail_loudly(html, filename, message):
    with pytest.raises(GoldSummaryError) as error:
        parse_export(html, filename)
    assert message in str(error.value) and filename in str(error.value)


def test_two_files_for_one_docket_fail_loudly(tmp_path):
    source = config.JUDGEMENTS_DIR / "Export_8C_72_2025.html"
    shutil.copy(source, tmp_path / "Export_8C_72_2025.html")
    shutil.copy(source, tmp_path / "Export_8C_72_2025 2.html")
    (tmp_path / "read.me").write_text("ignored")
    with pytest.raises(GoldSummaryError, match="more than one file for the same docket.*8C_72/2025"):
        read_gold_summaries(tmp_path)


# --- database ---------------------------------------------------------------------------------------


def add_ruling(conn, docket, decision_date, in_window=True) -> int:
    return conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES (%s, %s, %s, %s) RETURNING id",
        (docket, decision_date, docket.split("_")[0], in_window),
    ).fetchone()[0]


def summary(docket="8C_1/2025", date="2025-12-04", **changes) -> GoldSummary:
    base = GoldSummary(
        docket=docket,
        source_file=f"Export_{docket.replace('/', '_')}.html",
        title=f"BGer-Urteil {docket}",
        title_language="de",
        decision_date_from_title=date,
        body_de="Erster Absatz.\n\nZweiter Absatz.",
        body_fr="Premier paragraphe.",
        author="Muster Anna (MUA), Rechtsanwältin",
        source_url="https://search.bger.ch/x",
    )
    return dataclasses.replace(base, **changes)


def count(conn, table="gold_summaries") -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


SNAPSHOT_SQL = (
    "SELECT id, ruling_id, language, title, body, author, source_url, source_file, version, is_current, created_at"
    " FROM gold_summaries ORDER BY id"
)


@pytest.mark.db
def test_write_real_summaries_happy_path_and_idempotent(db_conn, real):
    for s in real:
        add_ruling(db_conn, s.docket, s.decision_date_from_title, in_window=s.decision_date_from_title >= "2025-10-01")

    assert write_gold_summaries(db_conn, real) == {"read": 55, "inserted": 110, "unchanged": 0}
    assert db_conn.execute(
        "SELECT count(*), count(DISTINCT ruling_id), count(*) FILTER (WHERE language = 'de'),"
        " count(*) FILTER (WHERE version = 1 AND is_current), count(*) FILTER (WHERE author IS NULL OR source_url IS NULL)"
        " FROM gold_summaries"
    ).fetchone() == (110, 55, 55, 110, 0)
    expected = next(s for s in real if s.docket == "8C_176/2025")
    rows = db_conn.execute(
        "SELECT g.language, g.title, g.body, g.author, g.source_url, g.source_file FROM gold_summaries g"
        " JOIN rulings r ON r.id = g.ruling_id WHERE r.docket = '8C_176/2025' ORDER BY g.language"
    ).fetchall()
    assert rows == [
        ("de", expected.title, expected.body_de, expected.author, expected.source_url, "Export_8C_176_2025 3.html"),
        ("fr", expected.title, expected.body_fr, expected.author, expected.source_url, "Export_8C_176_2025 3.html"),
    ]

    before = db_conn.execute(SNAPSHOT_SQL).fetchall()
    assert write_gold_summaries(db_conn, real) == {"read": 55, "inserted": 0, "unchanged": 110}
    assert db_conn.execute(SNAPSHOT_SQL).fetchall() == before


@pytest.mark.db
def test_changed_content_is_not_overwritten(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-04")
    write_gold_summaries(db_conn, [summary()])
    before = db_conn.execute(SNAPSHOT_SQL).fetchall()
    with pytest.raises(GoldSummaryError) as error:
        write_gold_summaries(db_conn, [summary(body_fr="Premier paragraphe, corrigé.")])
    assert "not overwritten" in str(error.value)
    assert "8C_1/2025 [fr]" in str(error.value) and "8C_1/2025 [de]" not in str(error.value)
    assert db_conn.execute(SNAPSHOT_SQL).fetchall() == before


@pytest.mark.db
def test_missing_ruling_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-04")
    with pytest.raises(GoldSummaryError) as error:
        write_gold_summaries(db_conn, [summary(), summary("8C_2/2025"), summary("9C_3/2025")])
    assert "no ruling for 2 docket(s)" in str(error.value)
    assert "8C_2/2025" in str(error.value) and "9C_3/2025" in str(error.value)
    assert count(db_conn) == 0


@pytest.mark.db
def test_ambiguous_docket_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-04")
    add_ruling(db_conn, "7B_1356/2025", "2026-01-26")
    add_ruling(db_conn, "7B_1356/2025", "2026-03-18")
    with pytest.raises(GoldSummaryError) as error:
        write_gold_summaries(db_conn, [summary(), summary("7B_1356/2025", "2026-01-26")])
    assert "more than one ruling" in str(error.value)
    assert "7B_1356/2025" in str(error.value) and "2026-03-18" in str(error.value)
    assert count(db_conn) == 0


@pytest.mark.db
def test_title_date_mismatch_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-04")
    add_ruling(db_conn, "8C_2/2025", "2025-12-05")
    with pytest.raises(GoldSummaryError) as error:
        write_gold_summaries(db_conn, [summary(), summary("8C_2/2025", "2025-12-04")])
    assert "not the ruling's decision date" in str(error.value)
    assert "8C_2/2025: title 2025-12-04, ruling 2025-12-05" in str(error.value)
    assert "8C_1/2025" not in str(error.value)
    assert count(db_conn) == 0


@pytest.mark.db
def test_unknown_title_date_is_accepted(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-04")
    assert write_gold_summaries(db_conn, [summary(date=None)]) == {"read": 1, "inserted": 2, "unchanged": 0}

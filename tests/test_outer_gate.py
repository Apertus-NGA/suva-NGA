"""The outer gate keeps a ruling when its subject area is accident, military or disability insurance.

No network, no database, no model: the examples are short strings in the three languages of the court.
"""

from __future__ import annotations

import inspect

import pytest

from src.triage import outer_gate as og

HEADER = (
    "Bundesgericht\n\nUrteil vom 1. Januar 2026\n\nBesetzung\nBundesrichter X.\n\n"
    "Gegenstand\n{subject},\n\nBeschwerde gegen das Urteil\n"
)
HEADER_FR = "Tribunal fédéral\n\nArrêt du 1er janvier 2026\n\nObjet\n{subject},\n\nrecours contre l'arrêt\n"
HEADER_IT = "Tribunale federale\n\nSentenza del 1° gennaio 2026\n\nOggetto\n{subject},\n\nricorso contro la sentenza\n"


@pytest.mark.parametrize(
    ("area", "expected"),
    [
        ("Unfallversicherung", "UV"),
        ("Assurance-accidents", "UV"),
        ("Assicurazione contro gli infortuni", "UV"),
        ("Militärversicherung", "MV"),
        ("Assurance militaire", "MV"),
        ("Assicurazione militare", "MV"),
        ("Invalidenversicherung", "IV"),
        ("Assurance-invalidité", "IV"),
        ("Assicurazione per l'invalidità", "IV"),
        ("Assicurazione per l’invalidità", "IV"),  # typographic apostrophe
        ("Invalidenversicherung*", "IV"),  # the star marks a ruling proposed for publication
        ("  unfallversicherung (Kausalzusammenhang)  ", "UV"),
    ],
)
def test_the_three_areas_are_recognised_in_three_languages(area, expected):
    decision = og.outer_gate(area)
    assert decision.kept is True
    assert decision.area == expected
    assert decision.reasons == (f"list_area:{expected}",)
    assert decision.reason_code is None


@pytest.mark.parametrize(
    "area",
    [
        "Arbeitslosenversicherung",
        "Ergänzungsleistung zur AHV/IV",
        "Prestations complémentaires à l'AVS/AI",
        "Krankenversicherung",
        "Berufliche Vorsorge",
        "Öffentliche Finanzen & Abgaberecht",
        "Vertragsrecht",
        "Strafrecht (allgemein)",
        "Gesundheitswesen & soziale Sicherheit",
    ],
)
def test_other_areas_are_dropped_with_a_reason_code(area):
    decision = og.outer_gate(area)
    assert decision.kept is False
    assert decision.reason_code == og.REASON_NOT_IN_AREA
    assert decision.net_decision().reason_code == og.REASON_NOT_IN_AREA  # accepted by the shared contract (G5)


@pytest.mark.parametrize(
    "subject",
    [
        "Prévoyance professionnelle (rente d'invalidité)",  # a pension case whose topic names invalidity
        "Berufliche Vorsorge (Invalidenrente; Arbeitsunfähigkeit)",
        "Militärpflichtersatz",  # military service exemption tax, not military insurance
        "Ergänzungsleistung zur AHV/IV (Rückerstattung)",
    ],
)
def test_look_alike_subjects_are_not_taken_for_one_of_the_three_areas(subject):
    assert og.classify_area(subject) is None
    assert og.outer_gate(None, HEADER.format(subject=subject)).kept is False


@pytest.mark.parametrize(
    ("template", "subject", "expected"),
    [
        (HEADER, "Unfallversicherung (Kausalzusammenhang)", "UV"),
        (HEADER_FR, "Assurance-invalidité (allocation pour impotent)", "IV"),
        (HEADER_IT, "Assicurazione contro gli infortuni (rendita d'invalidità)", "UV"),
        (HEADER_FR, "Assurance militaire (condition de recevabilité)", "MV"),
    ],
)
def test_the_header_subject_is_used_when_the_list_has_no_area(template, subject, expected):
    decision = og.outer_gate(None, template.format(subject=subject))
    assert decision.kept is True
    assert decision.area == expected
    assert decision.reasons == (f"header_area:{expected}",)


def test_either_source_is_enough():
    text = HEADER.format(subject="Unfall- und Invalidenversicherung (Prozessvoraussetzung)")
    decision = og.outer_gate("Gesundheitswesen & soziale Sicherheit", text)
    assert decision.kept is True
    assert decision.reasons == ("header_area:IV",)
    both = og.outer_gate("Unfallversicherung", text)
    assert both.area == "UV"  # the list's area is reported first
    assert both.reasons == ("list_area:UV", "header_area:IV")


@pytest.mark.parametrize("list_area", [None, "", "   "])
@pytest.mark.parametrize("text", [None, "", "Bundesgericht\n\nUrteil ohne Gegenstandszeile\n"])
def test_the_gate_fails_open_when_no_area_can_be_read(list_area, text):
    decision = og.outer_gate(list_area, text)
    assert decision.kept is True
    assert decision.flagged is True
    assert decision.area is None
    assert decision.reasons == (og.FLAG_UNDETERMINED,)


def test_a_readable_area_outside_the_three_is_not_a_reason_to_fail_open():
    decision = og.outer_gate(None, HEADER.format(subject="Arbeitslosenversicherung"))
    assert decision.kept is False
    assert decision.flagged is False


def test_the_gate_never_sees_a_docket_or_a_court():
    # G5: never exclude a ruling on its docket prefix. The gate cannot: it is not given one.
    assert list(inspect.signature(og.outer_gate).parameters) == ["list_area", "full_text"]


def test_measure_counts_kept_flagged_and_relevant():
    rows = [
        {"list_area": "Unfallversicherung", "full_text": None, "relevant": True},
        {"list_area": "Assurance-invalidité", "full_text": None, "relevant": False},
        {"list_area": "Vertragsrecht", "full_text": None, "relevant": True},
        {"list_area": None, "full_text": None},
    ]
    counts = og.measure(rows)
    assert counts["rulings"] == 4
    assert counts["kept"] == 3
    assert counts["flagged"] == 1
    assert counts["relevant"] == 2
    assert counts["relevant_kept"] == 1
    assert counts["by_area_UV"] == 1 and counts["by_area_IV"] == 1


REAL_HEADERS = [
    # Layout copied from three real rulings (German, French, Italian): the court's pages put a
    # non-breaking space after the heading and after the subject line.
    (" \n\nGegenstand \n\nUnfallversicherung (Kausalzusammenhang), \n\n \n\nBeschwerde ", "UV"),
    (" \n\nObjet \n\nAssurance-accidents (rente d'invalidité), \n\n \n\nrecours ", "UV"),
    (" \n\nOggetto \n\nAssicurazione per l'invalidità (diniego di giustizia), \n\n \n\nricorso ", "IV"),
]


@pytest.mark.parametrize(("text", "expected"), REAL_HEADERS)
def test_the_header_is_read_as_the_court_really_lays_it_out(text, expected):
    subject = og.header_subject(text)
    assert subject is not None and not subject.endswith((",", " "))
    decision = og.outer_gate(None, text)
    assert decision.reasons == (f"header_area:{expected}",)
    assert decision.flagged is False

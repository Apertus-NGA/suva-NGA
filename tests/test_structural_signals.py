"""Structural signals are read from the ruling's header in the court's real layout, in three languages.

No network, no database, no model. The headers below follow real rulings: non-breaking spaces after the
headings, anonymised persons as "A.________", institutions with their address.
"""

from __future__ import annotations

import pytest

from src.signals import structural as st

NB = " "

DE_INSURED_VS_SUVA = (
    f"Bundesgericht{NB}\n\nUrteil vom 1. Dezember 2025{NB}\n\nIV. öffentlich-rechtliche Abteilung{NB}\n\n"
    f"Besetzung{NB}\n\nBundesrichterin Viscione, Präsidentin,{NB}\n\nBundesrichterinnen Heine, Scherrer Reber,{NB}\n\n"
    f"Gerichtsschreiber Hochuli.{NB}\n\nVerfahrensbeteiligte{NB}\n\nA.________,{NB}\n\n"
    f"vertreten durch Rechtsanwalt B.________,{NB}\n\nBeschwerdeführer,{NB}\n\ngegen{NB}\n\n"
    f"Schweizerische Unfallversicherungsanstalt (Suva), Rechtsabteilung, Fluhmattstrasse 1, 6002 Luzern,{NB}\n\n"
    f"Beschwerdegegnerin.{NB}\n\nGegenstand{NB}\n\nUnfallversicherung (Kausalzusammenhang),{NB}\n\n"
    f"Beschwerde gegen das Urteil des Sozialversicherungsgerichts.{NB}\n\nSachverhalt:{NB}\n\nA.{NB}\n\n"
    "Der Versicherte verdrehte sich den Fuss. Die Suva stellte die Leistungen ein.\n\nErwägungen:\n\n1. "
    "Die Beschwerde ist offensichtlich unbegründet und wird im Verfahren nach Art. 109 Abs. 2 lit. a BGG erledigt.\n\n"
    "Demnach erkennt das Bundesgericht:\n\n1. Die Beschwerde wird abgewiesen.\n"
)
FR_INSURER_APPEALS_FIVE_JUDGES = (
    f"Tribunal fédéral{NB}\n\nArrêt du 19 novembre 2025{NB}\n\nIVe Cour de droit public{NB}\n\nComposition{NB}\n\n"
    f"Mmes et MM. les Juges fédéraux Viscione, Présidente, Maillard, Heine, Scherrer Reber et Métral.{NB}\n\n"
    f"Greffier : M. Ourny.{NB}\n\nParticipants à la procédure{NB}\n\n"
    f"Helsana Accidents SA, avenue de Provence 15, 1007 Lausanne,{NB}\n\nrecourante,{NB}\n\ncontre{NB}\n\n"
    f"A.________,{NB}\n\nreprésenté par Me B.________, avocate,{NB}\n\nintimé.{NB}\n\nObjet{NB}\n\n"
    f"Assurance-accidents (rente d'invalidité; restitution),{NB}\n\nrecours contre l'arrêt cantonal.{NB}\n\n"
    "Faits :\n\nA.\n\nL'assuré a été placé en détention.\n\nConsidérant en droit :\n\n1. Le recours est recevable.\n\n"
    "Par ces motifs, le Tribunal fédéral prononce :\n\n1. Le recours est admis.\n"
)
IT_SUVA_APPEALS = (
    f"Tribunale federale{NB}\n\nSentenza del 29 gennaio 2026{NB}\n\nComposizione{NB}\n\n"
    f"Giudici federali Viscione, Presidente, Maillard e Métral.{NB}\n\nCancelliere Colombi.{NB}\n\n"
    f"Partecipanti al procedimento{NB}\n\nIstituto nazionale svizzero di assicurazione contro gli infortuni (INSAI), "
    f"Divisione giuridica, Fluhmattstrasse 1, 6002 Lucerna,{NB}\n\nricorrente,{NB}\n\ncontro{NB}\n\nA.________,{NB}\n\n"
    f"opponente.{NB}\n\nOggetto{NB}\n\nAssicurazione contro gli infortuni (rendita d'invalidità),{NB}\n\n"
    "ricorso contro la sentenza del Tribunale cantonale.\n\n"
    "Fatti:\n\nA.\n\nL'assicurato è caduto.\n\nDiritto:\n\n1. ...\n"
)
DE_SINGLE_JUDGE = (
    f"Bundesgericht{NB}\n\nUrteil vom 2. Februar 2026{NB}\n\nBesetzung{NB}\n\n"
    f"Bundesrichterin Viscione, Präsidentin, als Einzelrichterin,{NB}\n\nGerichtsschreiber Grünenfelder.{NB}\n\n"
    f"Verfahrensbeteiligte{NB}\n\nA.________,{NB}\n\nBeschwerdeführerin,{NB}\n\ngegen{NB}\n\n"
    f"IV-Stelle des Kantons Zürich, Röntgenstrasse 17, 8005 Zürich,{NB}\n\nBeschwerdegegnerin.{NB}\n\n"
    f"Gegenstand{NB}\n\nInvalidenversicherung (Prozessvoraussetzung),{NB}\n\nBeschwerde gegen das Urteil.{NB}\n\n"
    "Erwägungen:\n\n1. Auf die Beschwerde wird nicht eingetreten.\n"
)


def values(text: str, list_area: str | None = None, starred: bool | None = False) -> dict:
    return st.as_dict(st.structural_signals(list_area, starred, text))


def test_german_ruling_insured_person_against_suva():
    v = values(DE_INSURED_VS_SUVA, "Unfallversicherung")
    assert v["area"] == "UV"
    assert v["bench_size"] == 3 and v["single_judge"] is False and v["five_judges"] is False
    assert v["appeal_by_institution"] is False
    assert v["suva_party"] is True and v["suva_appellant"] is False
    assert v["manifestly_unfounded"] is True
    assert v["proposed_for_publication"] is False


def test_french_ruling_insurer_appeals_before_five_judges():
    v = values(FR_INSURER_APPEALS_FIVE_JUDGES, "Assurance-accidents*", None)
    assert v["area"] == "UV"
    assert v["bench_size"] == 5 and v["five_judges"] is True
    assert v["appeal_by_institution"] is True
    assert v["suva_party"] is False and v["suva_appellant"] is False
    assert v["manifestly_unfounded"] is False
    assert v["proposed_for_publication"] is True  # the star on the list's area


def test_italian_ruling_suva_brings_the_appeal():
    v = values(IT_SUVA_APPEALS, None, None)
    assert v["area"] == "UV"  # read from the header when the list has no area
    assert v["bench_size"] == 3
    assert v["appeal_by_institution"] is True
    assert v["suva_party"] is True and v["suva_appellant"] is True
    assert v["proposed_for_publication"] == "unknown"  # the list was not seen: unknown, never False


def test_single_judge_disability_ruling():
    v = values(DE_SINGLE_JUDGE, "Invalidenversicherung")
    assert v["area"] == "IV"
    assert v["bench_size"] == 1 and v["single_judge"] is True
    assert v["appeal_by_institution"] is False
    assert v["suva_party"] is False


def test_suva_named_only_in_the_facts_is_not_a_party():
    text = DE_SINGLE_JUDGE.replace(
        "Erwägungen:", "Sachverhalt:\n\nDie Suva hatte Taggelder ausgerichtet.\n\nErwägungen:"
    )
    assert values(text)["suva_party"] is False


def test_every_signal_says_where_it_was_read():
    signals = st.structural_signals("Unfallversicherung", False, DE_INSURED_VS_SUVA)
    assert [s.name for s in signals] == [
        "area", "bench_size", "single_judge", "five_judges", "appeal_by_institution", "suva_appellant",
        "suva_party", "manifestly_unfounded", "proposed_for_publication",
    ]  # fmt: skip
    by_name = {s.name: s for s in signals}
    assert by_name["area"].evidence.field == "sachgebiet"
    span = by_name["manifestly_unfounded"].evidence
    assert DE_INSURED_VS_SUVA[span.start : span.end] == "offensichtlich unbegründet"
    party = by_name["suva_party"].evidence
    assert "Unfallversicherungsanstalt" in DE_INSURED_VS_SUVA[party.start : party.end]
    bench = by_name["bench_size"].evidence
    assert "Viscione" in DE_INSURED_VS_SUVA[bench.start : bench.end]


@pytest.mark.parametrize("text", [None, "", "Kurzer Text ohne Kopf."])
def test_a_ruling_without_a_readable_header_still_gets_signals(text):
    v = values(text, None, None)
    assert v["area"] == "other"
    assert v["suva_party"] is False and v["manifestly_unfounded"] is False
    assert v["proposed_for_publication"] == "unknown"
    assert "bench_size" not in v and "appeal_by_institution" not in v  # absent, not guessed

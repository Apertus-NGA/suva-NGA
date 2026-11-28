"""One reading of the court's matter names, in German, French and Italian."""

import pytest

from src.areas import area_code, first_segment


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Unfallversicherung", "UV"),
        ("Assurance-accidents*", "UV"),
        ("Assurance-accident", "UV"),
        ("Assicurazione contro gli infortuni", "UV"),
        ("Militärversicherung", "MV"),
        ("Assurance militaire", "MV"),
        ("Assicurazione militare", "MV"),
        ("Invalidenversicherung", "IV"),
        ("Assurance-invalidité", "IV"),
        ("Assicurazione per l'invalidità", "IV"),
        ("Assicurazione per l’invalidità", "IV"),  # typographic apostrophe
        ("Krankenversicherung", "KV"),
        ("Assurance-maladie", "KV"),
        ("Assicurazione malattie", "KV"),
        ("Assicurazione contro le malattie", "KV"),
        ("Berufliche Vorsorge", "BV"),
        ("Prévoyance professionnelle", "BV"),
        ("Previdenza professionale", "BV"),
        ("Previdenza professionnale", "BV"),  # as the court's page spells it
        ("Vertragsrecht", "CONTRACT"),
        ("Droit des contrats", "CONTRACT"),
        ("Diritto contrattuale", "CONTRACT"),
        ("Haftpflichtrecht", "LIABILITY"),
        ("Assurance responsabilité civile", "LIABILITY"),
    ],
)
def test_matter_names_in_three_languages(text, code):
    assert area_code(text) == code


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Arbeitslosenversicherung",
        "Ergänzungsleistung zur AHV/IV",
        "Finances publiques & droit fiscal",
        "Responsabilité de l'État",  # state liability, another rubric
        "Militärpflichtersatz",  # the exemption tax, not military insurance
        "contrat de travail",  # a dispute, not the contract-law rubric
        "Krankentaggeldversicherung",
    ],
)
def test_other_matters_have_no_code(text):
    assert area_code(text) is None


def test_only_the_matter_is_read_not_the_dispute_in_brackets():
    assert area_code("Prévoyance professionnelle (rente d'invalidité)") == "BV"
    assert area_code("Berufliche Vorsorge (Invalidenleistungen)") == "BV"
    assert area_code("Unfallversicherung; Invalidenversicherung") == "UV"
    assert first_segment("Invalidenversicherung, Invalidenrente") == "Invalidenversicherung"
    assert first_segment("  Assurance-accidents (lien de causalité),") == "Assurance-accidents"
    assert first_segment(" , ") is None

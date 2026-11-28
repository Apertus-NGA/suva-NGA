"""Deterministic finishing of a fiche (src/summarize/finish.py). No model, no network."""

import pytest

from src.summarize import finish as f

RULING = (
    "Besetzung\nBundesrichterin Viscione, Präsidentin,\nBundesrichter Maillard, Bundesrichterin Heine,\n"
    "Bundesrichter Métral, Bundesrichterin Scherrer Reber,\nGerichtsschreiber Wüest.\n\n"
    "Erwägungen:\n\n1.\nEintreten.\n\n4.\n4.1. Nach Art. 6 Abs. 2 UVG. Text.\n\n4.2. Text.\n\n"
    "Demnach erkennt das Bundesgericht:\n\n1.\nDie Beschwerde wird abgewiesen.\n\n2.\nDie Gerichtskosten werden auferlegt.\n"  # noqa: E501
)
SINGLE = "Composition\nMme la Juge fédérale Viscione, Présidente.\nGreffier : M. Ourny.\n\nPar ces motifs, la Présidente prononce :\n\n1.\nLe recours est irrecevable.\n"  # noqa: E501


def test_markdown_is_removed():
    assert f.strip_markdown("## Titel\n**Die Regel** gilt.\n- Punkt") == "Titel\nDie Regel gilt.\nPunkt"


@pytest.mark.parametrize(
    "language, text, expected",
    [
        (
            "de",
            "Nach art. 6 al. 2 LAA und art. 4 LPGA sowie OLAA.",
            "Nach Art. 6 Abs. 2 UVG und Art. 4 ATSG sowie UVV.",
        ),
        ("fr", "Selon Art. 6 Abs. 2 UVG et Art. 17 ATSG, lit. a.", "Selon art. 6 al. 2 LAA et art. 17 LPGA, let. a."),
        ("de", "Die Suva nach LAINF.", "Die Suva nach UVG."),
        ("de", "Der Versicherte bezog Taggelder.", "Der Versicherte bezog Taggelder."),
        ("fr", "La LAA et la LAMal restent.", "La LAA et la LAMal restent."),
    ],
)
def test_abbreviations_follow_the_language_of_the_fiche(language, text, expected):
    assert f.own_language_abbreviations(text, language) == expected


def test_only_considerations_that_exist_are_kept():
    text, dropped = f.real_considerations_only(
        "Regel eins (E. 4.2). Regel zwei (E. 7.3). Beide (E. 4.1 und 4.2).", RULING
    )
    assert text == "Regel eins (E. 4.2). Regel zwei. Beide (E. 4.1 und 4.2)."
    assert dropped == ["(E. 7.3)"]


def test_outcome_is_read_from_point_one_of_the_operative_part():
    assert f.outcome_kind(RULING) == "rejected"
    assert f.outcome_kind(SINGLE) == ""  # inadmissible: not one of the three outcomes written by code
    legal_aid = RULING.replace(
        "2.\nDie Gerichtskosten werden auferlegt.", "2.\nDas Gesuch um unentgeltliche Rechtspflege wird gutgeheissen."
    )
    assert f.outcome_kind(legal_aid) == "rejected"  # a later point does not change the outcome of the appeal
    assert f.outcome_kind("Kein Dispositiv.") == ""
    mixed = "Par ces motifs, le Tribunal fédéral prononce :\n\n1.\nLe recours est admis en ce sens que l'arrêt est annulé. Il est rejeté pour le surplus.\n\n2.\nLes frais.\n"  # noqa: E501
    assert f.outcome_kind(mixed) == "partial"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Die Regel gilt. Die Beschwerde wird abgewiesen.", "Die Regel gilt. Die Beschwerde wird abgewiesen."),
        ("Die Regel gilt.", "Die Regel gilt. Die Beschwerde wird abgewiesen."),
        (
            "Die Regel gilt. Das Bundesgericht wies die Beschwerde ab. Die Beschwerde wird abgewiesen.",
            "Die Regel gilt. Die Beschwerde wird abgewiesen.",
        ),
        ("Die Beschwerde wird abgewiesen.", "Die Beschwerde wird abgewiesen."),
        (
            "Die Beschwerde wird abgewiesen, weil die Kausalität nach der Regel fehlt.",
            "Die Beschwerde wird abgewiesen, weil die Kausalität nach der Regel fehlt.",
        ),
    ],
)
def test_outcome_appears_exactly_once(text, expected):
    assert f.outcome_once(text, "de", "rejected") == expected


def test_french_outcome_and_unknown_kind():
    assert f.outcome_once(
        "La règle vaut. Le Tribunal fédéral rejette le recours. Le recours est rejeté.", "fr", "rejected"
    ) == ("La règle vaut. Le recours est rejeté.")
    assert (
        f.outcome_once("La règle vaut. Le recours est irrecevable.", "fr", "")
        == "La règle vaut. Le recours est irrecevable."
    )


def test_judges_are_counted_from_the_heading():
    assert f.judges(RULING) == 5 and f.judges(SINGLE) == 1 and f.judges("no heading") is None


@pytest.mark.parametrize(
    "language, starred, expected",
    [
        ("de", True, "Fünfer-Entscheid, zur Publikation vorgesehen."),
        ("de", False, "Fünfer-Entscheid."),
        ("de", None, "Fünfer-Entscheid."),  # publication mark unknown: not claimed
        ("fr", True, "Décision à cinq, prévue pour publication."),
    ],
)
def test_bench_note_states_only_known_facts(language, starred, expected):
    assert f.bench_note(language, RULING, starred) == expected


def test_no_note_for_an_ordinary_ruling():
    assert f.bench_note("de", SINGLE, None) == "" and f.bench_note("fr", SINGLE, True) == "Prévue pour publication."


def test_finish_puts_it_together():
    draft = "**Die Regel** nach art. 6 al. 2 LAA gilt (E. 4.2), auch hier (E. 9.9). Das Bundesgericht wies die Beschwerde ab. Die Beschwerde wird abgewiesen."  # noqa: E501
    text, notes = f.finish("de", draft, RULING, starred=True)
    assert text == (
        "Die Regel nach Art. 6 Abs. 2 UVG gilt (E. 4.2), auch hier. Die Beschwerde wird abgewiesen.\n\n"
        "Fünfer-Entscheid, zur Publikation vorgesehen."
    )
    assert notes == ["abbreviations put in the fiche's language", "reference not in the ruling removed: (E. 9.9)"]


def test_finish_is_stable_when_applied_twice():
    once, _ = f.finish("de", "Die Regel gilt (E. 4.1).", RULING, starred=False)
    assert f.finish("de", once, RULING, starred=False)[0] == once


def test_an_article_missing_from_the_ruling_is_removed():
    text, dropped = f.cited_articles_in_the_ruling("Art. 6 Abs. 2 UVG gilt. Art. 99 ATSG gilt nicht.", RULING)
    assert text == "Art. 6 Abs. 2 UVG gilt. gilt nicht."
    assert dropped == ["Art. 99 ATSG"]


def test_manifestly_ill_founded_needs_either_language_in_the_ruling():
    bare = "Die Regel gilt. Die Beschwerde ist offensichtlich unbegründet."
    french_ruling = "Le recours est manifestement non fondé."
    kept, dropped = f.grounded_wording_only(bare, french_ruling)
    assert kept == bare and dropped is False
    removed, dropped = f.grounded_wording_only(bare, RULING)
    assert "offensichtlich" not in removed and dropped is True
    from src.summarize.summarize import blocking

    assert "critique: manifestly ill-founded copied" not in blocking("de", bare, french_ruling)
    assert "critique: manifestly ill-founded copied" in blocking(
        "fr", "Le recours est manifestement non fondé.", RULING
    )


def test_placeholder_is_reported_not_rewritten():
    text, notes = f.finish("de", "A.________ verlangte eine Rente nach der Regel.", SINGLE)
    assert "A.________" in text and notes == ["party placeholder left in the text"]

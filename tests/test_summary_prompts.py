"""The fiche prompt loads only the glossary of the ruling's matter."""

from src.summarize.prompts import VERSION, category_of, glossary_block, qwen_comparison, system_prompt
from src.summarize.summarize import blocking, write_fiche
from src.summarize.v1.prompts import VERSION as V1
from src.summarize.v1.prompts import system_prompt as system_v1


def test_versions_are_easy_to_tell_apart():
    assert V1 == "v1"
    assert VERSION == "v2"
    assert "UVG, ATSG, UVV" in system_v1("de")
    assert "Unfallversicherung" in system_prompt("de", "uv")
    assert "Invalidenversicherung" not in system_v1("de")


def test_category_follows_the_neuheiten_subject():
    assert category_of("Unfallversicherung") == "uv"
    assert category_of("Assurance-invalidité*") == "iv"
    assert category_of("Assicurazione malattie") == "kv"
    assert category_of("Prévoyance professionnelle") == "bv"
    assert category_of("Vertragsrecht") == "vvg"
    assert category_of("Arbeitslosenversicherung") == "other"


def test_glossary_stays_inside_the_category():
    uv = glossary_block("fr", "uv")
    iv = glossary_block("de", "iv")
    vvg = glossary_block("fr", "vvg")
    assert "LAA" in uv and "OLAA" in uv and "LPGA" in uv
    assert "LAI" not in uv and "LAMal" not in uv and "LPP" not in uv
    assert "IVG" in iv and "IVV" in iv and "ATSG" in iv
    assert "UVG" not in iv
    assert "LCA" in vvg and "LPGA" not in vvg and "LAA" not in vvg
    assert "Art. 6" not in uv


def test_operative_sentence_alone_is_a_problem():
    bare = "Die Beschwerde wird abgewiesen."
    found = blocking("de", bare, "Demnach erkennt das Bundesgericht: 1. " + bare)
    assert "critique: fiche is only the operative sentence" in found
    held = (
        "Die Suva hatte Prämien für Fremdarbeiten aufgerechnet. "
        "Das Bundesgericht wies die Beschwerde ab, weil die Feststellung nicht unrichtig war. "
        "Die Beschwerde wird abgewiesen."
    )
    assert "critique: fiche is only the operative sentence" not in blocking("de", held, bare)


def test_system_prompt_names_its_matter():
    assert "Unfallversicherung" in system_prompt("de", "uv")
    assert "Invalidenversicherung" in system_prompt("de", "iv")
    assert "Art. 17 ATSG" in system_prompt("de", "uv")
    assert "Art. 17" not in system_prompt("de", "vvg")
    assert "LPP" in system_prompt("fr", "bv")


def test_category_reads_the_matter_like_the_gate():
    # Real subject lines of 8C_44/2025, 8C_539/2025 and 9C_636/2025 (German, French, Italian).
    assert category_of("Invalidenversicherung, Invalidenrente") == "iv"
    assert category_of("Assurance-accident (assistance judiciaire gratuite; condition de recevabilité)s") == "uv"
    assert category_of("Assicurazione contro le malattie") == "kv"
    assert category_of("Militärversicherung") == "other"  # no glossary of its own
    assert category_of(None) == "other"


def test_qwen_comparison_stays_out_of_the_running_prompt():
    running = system_prompt("de", "uv") + system_prompt("fr", "iv")
    for line in qwen_comparison:
        assert line not in running
    joined = " ".join(qwen_comparison)
    assert "article number" in joined
    assert "operative outcome" in joined
    assert "offensichtlich" in joined and "manifestement" in joined
    seen: list[str] = []

    def ask(messages):
        seen.append(messages[0]["content"])
        return (
            "Der Versicherte verlangte eine Rente. Das Bundesgericht hielt die Feststellung für richtig. "
            "Die Beschwerde wird abgewiesen."
        )

    target = {
        "docket": "8C_1/2026",
        "decision_date": "2026-01-01",
        "division": "I",
        "area": "Unfallversicherung",
        "text": "Demnach erkennt das Bundesgericht: 1. Die Beschwerde wird abgewiesen.",
    }
    write_fiche("de", target, [], "uv", ask)
    assert qwen_comparison[0] not in seen[0]
    write_fiche("de", target, [], "uv", ask, extras=qwen_comparison)
    assert qwen_comparison[0] in seen[1]


def test_every_glossary_subject_is_read_as_its_own_matter():
    from src.summarize.v2.prompts import GLOSSARY

    for key, block in GLOSSARY.items():
        for subject in block.get("subjects", []):
            assert category_of(subject) == key, (key, subject)

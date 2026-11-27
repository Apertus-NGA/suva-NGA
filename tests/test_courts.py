"""The candidate gate keeps a missing subject and a text mention, and names both decisions."""

from src.courts import area_for_gate, decide, gate_record, passes, rubric_from_title


def test_subject_in_the_list_is_kept():
    gate = decide("8C_78/2025", "Unfallversicherung")
    assert gate.kept
    assert gate.subject == "kept_subject"
    assert gate.text == "text_absent"
    assert passes("4A_106/2025", "Vertragsrecht*")
    assert passes("9C_65/2025", "Assicurazione per l'invalidità")


def test_gate_record_stores_both_decisions():
    row = gate_record("8C_748/2024", "Arbeitslosenversicherung", None, "La CNA est intimée.")
    assert row == {
        "docket": "8C_748/2024",
        "subject": "subject_out",
        "text": "kept_text",
        "kept": True,
    }
    assert "CNA" not in row["text"]


def test_blank_area_takes_the_matter_from_the_title():
    assert rubric_from_title("Invalidenversicherung,") == "Invalidenversicherung"
    assert rubric_from_title("Assurance-accidents (lien de causalité),") == "Assurance-accidents"
    assert rubric_from_title("Unfallversicherung (Unfallkausalität),") == "Unfallversicherung"
    assert area_for_gate("Vertragsrecht", "bail à loyer,") == "Vertragsrecht"
    filled = area_for_gate(None, "Berufliche Vorsorge,")
    assert decide("9C_1/2025", filled).subject == "kept_subject"
    assert decide("4A_1/2025", area_for_gate(None, "contrat de travail,")).subject == "subject_out"


def test_missing_subject_on_an_allowed_court_is_kept():
    gate = decide("8C_1/2025", None)
    assert gate.kept
    assert gate.subject == "subject_missing"
    assert gate.text == "text_absent"
    assert decide("4A_1/2025", "   ").subject == "subject_missing"
    assert decide("9F_1/2025", None).kept


def test_a_blank_subject_does_not_rescue_another_court():
    gate = decide("7B_1/2025", None)
    assert not gate.kept
    assert gate.subject == "wrong_court"
    assert decide("4B_1/2025", "Vertragsrecht").subject == "wrong_letter"


def test_text_mention_keeps_a_subject_the_list_drops():
    plain = decide("8C_748/2024", "Arbeitslosenversicherung", "Le recours est rejeté.")
    assert not plain.kept
    assert plain.subject == "subject_out"
    assert plain.text == "text_clear"
    named = decide("8C_748/2024", "Arbeitslosenversicherung", "La CNA est intimée.")
    assert named.kept
    assert named.subject == "subject_out"
    assert named.text == "kept_text"
    other_court = decide("6B_1/2025", "Droit pénal", "application de l'art. 6 UVG")
    assert other_court.kept
    assert other_court.subject == "wrong_court"
    assert other_court.text == "kept_text"

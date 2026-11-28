"""The candidate gate keeps a missing subject and a text mention, and names both decisions."""

from src import courts
from src.courts import area_for_gate, decide, gate_record, layer1_record, passes, rubric_from_title


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
        "subject_pass": False,
        "subject_criterion": "arbeitslosenversicherung",
        "text": "kept_text",
        "text_pass": True,
        "text_criterion": "cna",
        "text_blocked_term": None,
        "path": "text_only",
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


# --- Real rulings (docket and subject line as published). Each failed on the gate of commit 2d127cb.


def test_title_with_a_comma_or_semicolon_still_gives_the_matter():
    # German, 8C_44/2025 and 8C_542/2025: the matter is followed by a comma or a semicolon, not a bracket.
    assert gate_record("8C_44/2025", None, "Invalidenversicherung, Invalidenrente", None)["subject"] == "kept_subject"
    both = gate_record("8C_542/2025", None, "Unfallversicherung; Invalidenversicherung", None)
    assert both["subject"] == "kept_subject"
    assert rubric_from_title("Invalidenversicherung, Invalidenrente") == "Invalidenversicherung"


def test_matter_is_matched_by_name_not_by_exact_string():
    # French, 8C_539/2025: the court wrote the singular, and a stray letter follows the bracket.
    title = "Assurance-accident (assistance judiciaire gratuite; condition de recevabilité)s"
    assert gate_record("8C_539/2025", None, title, None)["subject"] == "kept_subject"
    # Italian, 9C_636/2025: the Neuheiten rubric is "contro le malattie", not "malattie".
    assert decide("9C_636/2025", "Assicurazione contro le malattie").subject == "kept_subject"


def test_court_4_title_is_not_a_rubric_so_a_blank_rubric_stays_unknown_and_kept():
    # On court 4 the title is the dispute ("contrat de travail"), never the rubric ("Droit des contrats").
    for docket, title in (
        ("4A_625/2025", "Arbeitsvertrag im Konzern; Aufhebungsvereinbarung"),  # German
        ("4A_424/2025", "contrat de travail"),  # French
        ("4A_179/2026", "risarcimento danni; assistenza giudiziaria"),  # Italian
    ):
        row = gate_record(docket, None, title, None)
        assert row["kept"] and row["subject"] == "subject_unknown", (docket, row)
    # A rubric read from the list is still decided: debt enforcement on court 4 is out.
    assert decide("4A_1/2025", "Schuldbetreibungs- und Konkursrecht").subject == "subject_out"


TAX_TITLE = "Staats- und Gemeindesteuern des Kantons Zürich und direkte Bundessteuer, Steuerperiode 2023"


class FakeJudge:
    """DECLARED FAKE (G9): stands in for the Apertus reading (src/area_judge.gate_judge). Records its calls."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def __call__(self, text, allowed):
        self.calls.append((text, allowed))
        if self.error:
            raise self.error
        return self.answer


OUT = {"apertus": "apertus_out", "matter": "OTHER", "in_scope_probability": 0.01, "kept": False}
IN = {"apertus": "kept_apertus", "matter": "IV", "in_scope_probability": 0.97, "kept": True}


def test_a_title_that_names_no_kept_matter_is_not_decided_by_code_on_any_court():
    # 9C_333/2026 (tax) and 4A_424/2025: no rubric, and the title names no matter of the list.
    for docket, title in (("9C_333/2026", TAX_TITLE), ("4A_424/2025", "contrat de travail")):
        gate = decide(docket, None, None, title)
        assert gate.subject == "subject_unknown" and gate.kept and gate.needs_apertus
    assert decide("8C_1/2026", None, None, None).needs_apertus  # no title either
    assert not decide("8C_78/2025", "Unfallversicherung").needs_apertus  # decided by the rubric
    assert not decide("9C_1/2025", "Finances publiques & droit fiscal").needs_apertus  # a rubric outside the list: out
    assert not decide("6B_1/2025", None, None, "Strafrecht").needs_apertus  # another court fails at once
    assert not decide("9C_333/2026", None, "La CNA est intimée.", TAX_TITLE).needs_apertus  # the text already keeps it


def test_apertus_decides_the_rulings_code_could_not_read():
    text = "Bundesgericht 9C_333/2026 ... " * 20
    dropped = layer1_record("9C_333/2026", None, TAX_TITLE, text, FakeJudge(OUT))
    assert dropped == {
        "docket": "9C_333/2026",
        "subject": "subject_unknown",
        "text": "text_clear",
        "apertus": "apertus_out",
        "matter": "OTHER",
        "in_scope_probability": 0.01,
        "kept": False,
    }
    judge = FakeJudge(IN)
    kept = layer1_record("8C_1/2026", None, None, text, judge)
    assert kept["subject"] == "subject_missing" and kept["apertus"] == "kept_apertus" and kept["kept"]
    assert judge.calls == [(text, courts.SOCIAL)]  # the ruling text and the matters kept on that court


def test_a_failed_or_absent_apertus_reading_keeps_the_ruling():
    text = "Tribunal fédéral 4A_424/2025 ... " * 20
    failed = layer1_record("4A_424/2025", None, "contrat de travail", text, FakeJudge(error=RuntimeError("timeout")))
    assert failed["apertus"] == "failed" and failed["kept"] and failed["matter"] is None
    pending = layer1_record("4A_424/2025", None, "contrat de travail", text, None)
    assert pending["apertus"] == "pending" and pending["kept"]


def test_apertus_is_not_asked_when_code_already_decided():
    judge = FakeJudge(OUT)
    text = "x" * 500
    assert layer1_record("8C_78/2025", "Unfallversicherung", None, text, judge)["apertus"] == "not_asked"
    assert layer1_record("6B_1/2025", None, "Strafrecht", text, judge)["kept"] is False
    assert layer1_record("9C_1/2025", "Finances publiques & droit fiscal", None, text, judge)["kept"] is False
    named = layer1_record("9C_333/2026", None, TAX_TITLE, "La CNA est intimée. " * 30, judge)
    assert named["kept"] and named["apertus"] == "not_asked"
    assert judge.calls == []


def test_text_rule_reads_the_long_forms_too():
    assert decide("6B_1/2025", "Strafrecht", "nach dem Unfallversicherungsgesetz").text == "kept_text"
    assert decide("4A_1/2025", "Gesellschaftsrecht", "l'assureur-accidents a versé").text == "kept_text"
    assert decide("5A_1/2025", "Familienrecht", "Der Unfallversicherer leistete Taggelder.").text == "kept_text"
    assert decide("5A_1/2025", "Familienrecht", "Das Unfallrisiko war bekannt.").text == "text_clear"


def test_insurance_contract_terms_keep_a_subject_the_list_drops():
    contract = decide("4A_1/2025", "Obligationenrecht (allgemein)", "Art. 14 Abs. 2 VVG.")
    assert contract.kept
    assert contract.subject == "subject_out"
    assert contract.text == "kept_contract"
    daily = decide("4A_2/2025", "Gesellschaftsrecht", "Die Taggeldversicherung deckt den Ausfall.")
    assert daily.kept
    assert daily.text == "kept_contract"
    french = decide("7B_1/2025", "Procédure pénale", "art. 95c LCA (RS 221.229.1)")
    assert french.kept
    assert french.text == "kept_contract"


def test_unemployment_daily_allowance_stays_out():
    bare = decide("8C_748/2024", "Arbeitslosenversicherung", "Das Taggeld wird gekürzt.")
    assert not bare.kept
    assert bare.subject == "subject_out"
    assert bare.text == "text_clear"
    statute = decide("8C_748/2024", "Arbeitslosenversicherung", "Art. 14 Abs. 2 VVG.")
    assert not statute.kept
    assert statute.text == "text_clear"
    assert statute.text_criterion == "arbeitslos"
    assert statute.text_blocked_term == "vvg"
    french = decide("8C_1/2025", "Assurance-chômage", "les indemnités journalières sont réduites")
    assert not french.kept
    assert french.text == "text_clear"
    named = decide("8C_748/2024", "Arbeitslosenversicherung", "La CNA est intimée. Art. 14 VVG.")
    assert named.kept
    assert named.text == "kept_text"


def test_layer1_is_written_in_batches(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from src.courts import write_layer1

    source = tmp_path / "rulings.parquet"
    dest = tmp_path / "layer1.json"
    rows = [
        {"docket": "8C_1/2025", "area": "Unfallversicherung", "subject": "Unfallversicherung,", "text": "x"},
        {"docket": "7B_1/2025", "area": "Droit pénal", "subject": "Droit pénal,", "text": "rien"},
        {"docket": "4A_1/2025", "area": "Obligationenrecht (allgemein)", "subject": "x", "text": "Art. 14 Abs. 2 VVG."},
        {"docket": "8C_2/2025", "area": None, "subject": "Berufliche Vorsorge,", "text": None},
        {"docket": "5A_1/2025", "area": "Erbrecht", "subject": "Erbrecht,", "text": "y"},
    ]
    pq.write_table(pa.Table.from_pylist(rows), source)
    seen, kept = write_layer1(source, dest, batch_size=2)
    assert (seen, kept) == (5, 3)
    import json

    log = json.loads(dest.read_text(encoding="utf-8"))
    assert log["schema_version"] == "layer1-log-1"
    assert log["population"] == {
        "unit": "ruling",
        "assets_in": 5,
        "assets_out": 3,
        "assets_dropped": 2,
        "keep": {"count": 3, "of": 5},
        "drop": {"count": 2, "of": 5},
    }
    subject, text, disposition = log["actions"]
    assert (subject["assets_in"], subject["assets_out"], subject["assets_dropped"]) == (5, 2, 3)
    assert (text["assets_in_scope"], text["assets_out"], text["assets_dropped"]) == (3, 1, 2)
    assert text["outside_scope"] == 2
    assert (disposition["assets_out"], disposition["assets_dropped"]) == (3, 2)
    assert log["quality"]["all_checks_passed"] is True
    assert all(ok for action in log["actions"] for ok in action["checks"].values())
    assert len(log["assets"]) == 5
    assert log["assets"][2]["deciding_action"] == "layer1.text"
    assert log["assets"][2]["actions"][1]["reason"] == "kept_contract"
    assert log["assets"][2]["actions"][1]["criterion"] == "vvg"
    assert log["assets"][1]["actions"][0]["criterion"] == "7"
    assert all(action["criterion"] for asset in log["assets"] for action in asset["actions"])
    assert log["run"]["output"] == {"log": str(dest)}
    assert not dest.with_suffix(".parquet").exists()
    limited = tmp_path / "limited.json"
    assert write_layer1(source, limited, limit=2, batch_size=2) == (2, 1)

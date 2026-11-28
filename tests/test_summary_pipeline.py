"""Summary pipeline version 1: routing to the prompt of the matter, finishing, storing (src/summarize/pipeline.py).

Mock declared (AGENTS.md G9): `FakeModel` stands in for Apertus. It records every prompt it is sent and
answers with a fixed fiche per language. No network; the database is the real test database.
"""

import pytest

from src.summarize import pipeline
from src.summarize.prompts import system_prompt

pytestmark = pytest.mark.db

RULING_DE = (
    "Bundesgericht\n\n8C_900/2025\n\nUrteil vom 3. März 2026\n\nBesetzung\nBundesrichterin Viscione, Präsidentin,\n"
    "Bundesrichter Maillard, Bundesrichterin Heine,\nGerichtsschreiber Wüest.\n\nSachverhalt:\nA.________ verunfallte.\n\n"  # noqa: E501
    "Erwägungen:\n\n4.\n4.1. Nach Art. 6 Abs. 1 UVG werden die Versicherungsleistungen bei Unfällen gewährt.\n\n4.2. Hier fehlt "  # noqa: E501
    "der natürliche Kausalzusammenhang.\n\nDemnach erkennt das Bundesgericht:\n\n1.\nDie Beschwerde wird abgewiesen.\n\n"  # noqa: E501
    "2.\nDie Gerichtskosten werden dem Beschwerdeführer auferlegt.\n\nLuzern, 3. März 2026\n\nIm Namen der IV. öffentlich-rechtlichen "  # noqa: E501
    "Abteilung des Schweizerischen Bundesgerichts\n\nDie Präsidentin: Viscione\n\nDer Gerichtsschreiber: Wüest\n"
)
FICHE = {
    "de": "Die Leistungspflicht nach art. 6 al. 1 LAA setzt einen natürlichen Kausalzusammenhang voraus (E. 4.1), der hier fehlt "  # noqa: E501
    "(E. 9.9). Das Bundesgericht wies die Beschwerde ab. Die Beschwerde wird abgewiesen.",
    "fr": "L'obligation de prester selon Art. 6 Abs. 1 UVG suppose un lien de causalité naturelle (consid. 4.1), qui fait défaut ici. "  # noqa: E501
    "Le recours est rejeté.",
}


class FakeModel:
    def __init__(self, answers=None):
        self.answers, self.calls = answers or FICHE, []

    def __call__(self, messages):
        self.calls.append(messages)
        user = messages[1]["content"]
        return self.answers[
            "de" if "ausschliesslich Deutsch" in user or user.lstrip().startswith("Überarbeite") else "fr"
        ]


def _ruling(conn, docket="8C_900/2025", area="Unfallversicherung", subject=None, text=RULING_DE, starred=None):
    rid = conn.execute(
        """INSERT INTO rulings (docket, decision_date, division, language, area, subject, starred, in_window)
           VALUES (%s, '2026-03-03', %s, 'de', %s, %s, %s, true) RETURNING id""",
        (docket, docket.split("_")[0], area, subject, starred),
    ).fetchone()[0]
    if text is not None:
        src = conn.execute(
            "INSERT INTO source_records (source, source_key, docket) VALUES ('swiss_caselaw', %s, %s) RETURNING id",
            (docket, docket),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO ruling_texts
                   (source_record_id, ruling_id, source, text, sha256_normalized, char_count, is_canonical)
               VALUES (%s, %s, 'swiss_caselaw', %s, %s, %s, true)""",
            (src, rid, text, "0" * 64, len(text)),
        )
    return rid


def _summaries(conn, rid):
    return conn.execute(
        "SELECT language, version, origin, is_current, body FROM summaries WHERE ruling_id = %s ORDER BY language, version",  # noqa: E501
        (rid,),
    ).fetchall()


# --- routing ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("area, expected", [
    ("Unfallversicherung", "uv"), ("Assurance-accidents", "uv"), ("Assicurazione contro gli infortuni", "uv"),
    ("Invalidenversicherung", "iv"), ("Assurance-invalidité", "iv"), ("Assicurazione per l'invalidità", "iv"),
    ("Krankenversicherung", "kv"), ("Assurance-maladie", "kv"), ("Assicurazione contro le malattie", "kv"),
    ("Berufliche Vorsorge", "bv"), ("Prévoyance professionnelle", "bv"),
    ("Vertragsrecht", "vvg"), ("Droit des contrats", "vvg"),
    ("Unfallversicherung*", "uv"),  # the publication star of the court's list
    ("Arbeitslosenversicherung", "other"), ("Strafprozess", "other"), ("Militärversicherung", "other"), (None, "other"), ("", "other"),  # noqa: E501
])  # fmt: skip
def test_route_by_area_in_three_languages(area, expected):
    assert pipeline.route(area) == expected


@pytest.mark.parametrize(
    "area, category, marker",
    [
        ("Unfallversicherung", "uv", "Matter: Unfallversicherung"),
        ("Assurance-invalidité", "iv", "Invalidenversicherung"),
        ("Strafprozess", "other", "Matter not classified"),
    ],
)
def test_each_ruling_is_sent_the_prompt_of_its_own_matter(db_conn, area, category, marker):
    rid = _ruling(db_conn, area=area)
    model = FakeModel()
    result = pipeline.summarise_ruling(db_conn, rid, ask=model, model="test-model")
    assert result["category"] == category
    systems = {call[0]["content"] for call in model.calls}
    assert systems == {
        system_prompt("de", category),
        system_prompt("fr", category),
    }  # exactly the two prompts of this matter
    assert any(marker in s for s in systems)
    for other in set(pipeline.CATEGORIES) - {category}:
        assert system_prompt("de", other) not in systems
    params = db_conn.execute("SELECT params FROM model_runs WHERE kind = 'summary'").fetchone()[0]
    assert (params["category"], params["pipeline"], params["prompt"]) == (category, "1", "v2")


def test_area_is_read_from_the_subject_line_when_the_court_list_is_missing(db_conn):
    rid = _ruling(db_conn, area=None, subject="Assurance-accidents (rente d'invalidité)")
    assert pipeline.load_ruling(db_conn, rid)["area"] == "Assurance-accidents"
    assert pipeline.routes(db_conn) == [(rid, "8C_900/2025", "Assurance-accidents", "uv")]


def test_the_ruling_text_reaches_the_model_and_the_ruling_is_not_its_own_example(db_conn):
    rid = _ruling(db_conn, docket="8C_177/2025")  # one of the pipeline's two fixed example rulings
    other = _ruling(db_conn, docket="8C_224/2025", text=None)
    for ruling_id in (rid, other):
        for language in ("de", "fr"):
            db_conn.execute(
                "INSERT INTO gold_summaries (ruling_id, language, title, body) VALUES (%s, %s, 'T', %s)",
                (ruling_id, language, f"Suva-Text {ruling_id} {language}"),
            )
    model = FakeModel()
    pipeline.summarise_ruling(db_conn, rid, ask=model, model="test-model")
    first_user = model.calls[0][1]["content"]
    assert "natürliche Kausalzusammenhang" in first_user  # the ruling itself
    assert f"Suva-Text {other} de" in first_user and f"Suva-Text {rid} de" not in first_user


# --- finishing and storing ------------------------------------------------------------------------------------


def test_fiches_are_finished_by_code_and_stored_with_their_run(db_conn):
    rid = _ruling(db_conn)
    result = pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="apertus-test")
    de, fr = (row[4] for row in _summaries(db_conn, rid))
    # outcome once, abbreviations in the fiche's language, the consideration that does not exist removed
    assert de == (
        "Die Leistungspflicht nach Art. 6 Abs. 1 UVG setzt einen natürlichen Kausalzusammenhang voraus (E. 4.1), der hier fehlt. "  # noqa: E501
        "Die Beschwerde wird abgewiesen."
    )
    assert fr == (
        "L'obligation de prester selon art. 6 al. 1 LAA suppose un lien de causalité naturelle (consid. 4.1), qui fait défaut ici. "  # noqa: E501
        "Le recours est rejeté."
    )
    assert [(r[0], r[1], r[2], r[3]) for r in _summaries(db_conn, rid)] == [
        ("de", 1, "model", True),
        ("fr", 1, "model", True),
    ]
    models, params = db_conn.execute(
        "SELECT models, params FROM model_runs WHERE id = %s", (result["stored"]["run_id"],)
    ).fetchone()
    assert models == [{"name": "apertus-test", "role": "writes the German and French fiche"}]
    assert params["finish_notes"]["de"] == [
        "abbreviations put in the fiche's language",
        "reference not in the ruling removed: (E. 9.9)",
    ]
    assert result["languages"]["de"]["raw"] == FICHE["de"]  # what the model wrote is returned too


def test_five_judge_published_ruling_gets_suvas_closing_note(db_conn):
    five = RULING_DE.replace(
        "Bundesrichter Maillard, Bundesrichterin Heine,",
        "Bundesrichter Maillard, Bundesrichterin Heine,\nBundesrichter Métral, Bundesrichterin Scherrer Reber,",
    )  # noqa: E501
    rid = _ruling(db_conn, text=five, starred=True)
    pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="m")
    de, fr = (row[4] for row in _summaries(db_conn, rid))
    assert de.endswith("Die Beschwerde wird abgewiesen.\n\nFünfer-Entscheid, zur Publikation vorgesehen.")
    assert fr.endswith("Le recours est rejeté.\n\nDécision à cinq, prévue pour publication.")
    problems = db_conn.execute("SELECT params -> 'problems' FROM model_runs").fetchone()[0]
    assert not any(
        "outcome" in p for p in problems["de"] + problems["fr"]
    )  # the note does not hide the outcome from the checker


def test_generating_again_makes_a_new_version_and_keeps_the_old_one(db_conn):
    rid = _ruling(db_conn)
    pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="m")
    second = pipeline.summarise_ruling(
        db_conn,
        rid,
        ask=FakeModel({"de": "Neue Regel gilt hier ebenfalls.", "fr": "La nouvelle règle vaut."}),
        model="m",
    )
    assert second["stored"]["versions"] == {"de": 2, "fr": 2}
    assert [(r[0], r[1], r[3]) for r in _summaries(db_conn, rid)] == [
        ("de", 1, False),
        ("de", 2, True),
        ("fr", 1, False),
        ("fr", 2, True),
    ]


def test_an_experts_fiche_is_never_replaced_as_the_current_one(db_conn):
    rid = _ruling(db_conn)
    pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="m")
    db_conn.execute("UPDATE summaries SET is_current = false WHERE ruling_id = %s AND language = 'de'", (rid,))
    db_conn.execute(
        "INSERT INTO summaries (ruling_id, language, body, origin, version) VALUES (%s, 'de', 'Von der Expertin bestätigt.', 'expert', 2)",  # noqa: E501
        (rid,),
    )
    result = pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="m")
    assert result["stored"]["current"] == {"de": False, "fr": True}
    rows = _summaries(db_conn, rid)
    assert [(r[1], r[2], r[3]) for r in rows if r[0] == "de"] == [
        (1, "model", False),
        (2, "expert", True),
        (3, "model", False),
    ]
    assert [r[4] for r in rows if r[0] == "de" and r[3]] == ["Von der Expertin bestätigt."]


def test_nothing_is_stored_when_the_model_fails_on_the_second_language(db_conn):
    rid = _ruling(db_conn)

    def failing(messages):
        if "Write in French only" in messages[1]["content"]:
            raise SystemExit("gateway: timeout")
        return FICHE["de"]

    with pytest.raises(SystemExit):
        pipeline.summarise_ruling(db_conn, rid, ask=failing, model="m")
    assert _summaries(db_conn, rid) == [] and db_conn.execute("SELECT count(*) FROM model_runs").fetchone()[0] == 0


def test_a_ruling_without_text_or_unknown_is_refused_before_any_call(db_conn):
    rid = _ruling(db_conn, text=None)
    model = FakeModel()
    with pytest.raises(pipeline.NotSummarisable, match="no usable text"):
        pipeline.summarise_ruling(db_conn, rid, ask=model, model="m")
    with pytest.raises(pipeline.NotSummarisable):
        pipeline.summarise_ruling(db_conn, 10_000_000, ask=model, model="m")
    assert model.calls == []


def test_summarised_rulings_show_up_in_the_summaries_view(db_conn):
    from suva_app import queries
    from suva_app.queries import RulingFilters

    rid = _ruling(db_conn)
    _ruling(db_conn, docket="8C_901/2025")
    pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="m")
    rows = queries.list_rulings(db_conn, RulingFilters(summarised=True))["items"]
    assert [r["docket"] for r in rows] == ["8C_900/2025"] and rows[0]["has_summary"] is True
    assert queries.learning(db_conn)["generated_summaries"] == 1

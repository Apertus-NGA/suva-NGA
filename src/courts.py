"""Candidate gate for the Suva score.

The court digits, the proceedings letters and the kept subjects are in
``docs/DATA.md`` §5. ``decide`` stores two decisions. The subject decision
keeps a ruling when its digit, its letter and its Neuheiten subject are in
that set. The subject is matched by name (``src/areas.py``), in German, French
or Italian. It is read from the Neuheiten rubric, and when that is empty from
the start of the ruling's subject line. The text decision keeps it when the text names Suva, CNA, INSAI or an accident or
military insurance term, and also when the text names the insurance-contract
act (VVG, LCA) or private daily-allowance insurance (Taggeldversicherung).
The bare word Taggeld does not: it is the unemployment benefit. Those
contract terms do not keep unemployment, old-age, tax, supplementary
benefits, loss-of-earnings, social assistance or family allowances.
Either decision is enough. A trailing asterisk on the subject (proposed for
the official reporter) is ignored.

Code drops a ruling on its subject only when the Neuheiten rubric names a
matter outside the set. When the rubric is empty and the subject line names no
kept matter (``subject_unknown``), or there is no subject line
(``subject_missing``), code does not decide: ``layer1_record`` asks Apertus to
read the matter (``src/area_judge.py``). Without an answer the ruling is kept.
The measured counts are in ``docs/LAYER1.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC

try:  # imported as ``src.courts`` by the tests, as ``courts`` by the scripts launched from src/
    from .areas import area_code, first_segment
except ImportError:
    from areas import area_code, first_segment

LETTERS = {
    "8": frozenset("CDFG"),
    "9": frozenset("CDFG"),
    "4": frozenset("ADFG"),
}

# Matters kept per court, as codes of ``src/areas.py`` (the names in three languages are there).
SOCIAL = frozenset({"UV", "MV", "IV", "KV", "BV"})
CONTRACT = frozenset({"CONTRACT", "LIABILITY"})
AREAS = {
    "8": SOCIAL,
    "9": SOCIAL,
    "4": CONTRACT,
}

# Accident or military insurance, and the insurer's names. Short forms need a word boundary.
_TEXT_TERMS = re.compile(
    r"\b(?:"
    r"suva|cna|insai|uvg|laa|lainf|mvg|"
    r"unfallversicherung(?:sgesetz|en)?|unfallversicherers?|unfallversicherern|militärversicherung|"
    r"assurance-accidents?|assureurs?-accidents?|assurance militaire|"
    r"assicurazione (?:contro gli )?infortuni|assicuratore infortuni|assicurazione militare"
    r")\b"
)
_SUBJECT_UNREAD = frozenset({"subject_missing", "subject_unknown"})  # code could not read the matter
_SUBJECT_KEEPS = frozenset({"kept_subject"}) | _SUBJECT_UNREAD
_TEXT_KEEPS = frozenset({"kept_text", "kept_contract"})

# Private daily-allowance insurance and the Insurance Contract Act.
# Bare "Taggeld" is the unemployment benefit and is not a term.
_CONTRACT_TERMS = re.compile(
    r"(?:taggeldversicherung|"
    r"\bvvg\b|\blca\b|"
    r"versicherungsvertragsgesetz|"
    r"loi sur le contrat d['’]assurance|"
    r"legge (?:federale )?sul contratto d['’]assicurazione)"
)
# Rubrics the contract terms must not pull back in. Stems cover the
# spellings measured in the local cache, including a tax title taken
# from the start of ``title`` when ``legal_area`` is empty.
_CLOSED_RUBRIC = re.compile(
    r"arbeitslos|chômage|chomage|disoccupaz|"
    r"alters- und hinterlassenen|vieillesse|vecchiaia|"
    r"ergänzungsleistung|prestations complémentaires|prestazion\w* complementar|"
    r"sozialhilfe|aide sociale|assistenza sociale|"
    r"familienzulag|allocations familiales|assegni familiari|"
    r"erwerbsersatz|erwerbersatz|perte de gain|perdita di guadagno|"
    r"finanzen & abgabe|finances publiques|finanze pubbliche|"
    r"impôt|imposta|umsatzabgabe|droit fiscal|diritto tributario"
)


@dataclass(frozen=True)
class Gate:
    """The subject decision and the text decision, kept apart.

    ``subject_criterion`` and ``text_criterion`` are the value that matched:
    the rubric, the court digit, the letter, the term, or the named rule
    (``blank_rubric``, ``empty_text``, ``no_keep_term``). ``text_blocked_term``
    is a contract term that matched and was refused because the rubric is closed.
    """

    kept: bool
    subject: str
    text: str
    subject_criterion: str
    text_criterion: str
    text_blocked_term: str | None = None

    @property
    def needs_apertus(self) -> bool:
        """Code could not read the matter and the text decision did not keep the ruling."""
        return self.subject in _SUBJECT_UNREAD and self.text not in _TEXT_KEEPS


def court_of(docket: str) -> str:
    """Prefix before the underscore, for example ``8C``."""
    return docket.split("_", 1)[0]


def _subject(area: str) -> str:
    return area.strip().casefold().rstrip("*").strip()


def _missing(area: object) -> bool:
    return not isinstance(area, str) or not area.strip()


def rubric_from_title(title: object) -> str | None:
    """Matter at the start of ``title``, the column just before ``legal_area``.

    When Hugging Face leaves ``legal_area`` empty it still writes
    ``Invalidenversicherung,``, ``Assurance-accidents (lien de causalité),`` or
    ``Invalidenversicherung, Invalidenrente`` in ``title``. The matter ends at the first
    bracket, comma or semicolon. The following column, ``regeste``, is empty on those rows.
    """
    return first_segment(title)


def area_for_gate(area: object, title: object = None) -> object:
    """Use ``area`` when it is filled, otherwise the matter parsed from ``title``."""
    if not _missing(area):
        return area
    return rubric_from_title(title)


def _hit(pattern: re.Pattern[str], value: str) -> str | None:
    found = pattern.search(value)
    return found.group(0) if found else None


def _subject_decision(docket: str, area: object, title: object = None) -> tuple[str, str]:
    head = court_of(docket)
    if len(head) != 2:
        return "wrong_court", head or "empty_prefix"
    division, letter = head[0], head[1]
    allowed = AREAS.get(division)
    if allowed is None:
        return "wrong_court", division
    if letter not in LETTERS[division]:
        return "wrong_letter", letter
    if not _missing(area):
        rubric = _subject(area)
        return ("kept_subject" if area_code(area) in allowed else "subject_out"), rubric
    matter = rubric_from_title(title)
    if matter is None:
        return "subject_missing", "blank_rubric"
    # A title often names the dispute ("contrat de travail", "Rechtsverweigerung"), not the matter:
    # when it names no kept matter, nothing was read.
    if area_code(matter) in allowed:
        return "kept_subject", _subject(matter)
    return "subject_unknown", _subject(matter)


def _text_decision(text: object, area: object = None) -> tuple[str, str, str | None]:
    if not isinstance(text, str) or not text.strip():
        return "text_absent", "empty_text", None
    folded = text.casefold()
    accident = _hit(_TEXT_TERMS, folded)
    if accident:
        return "kept_text", accident, None
    contract = _hit(_CONTRACT_TERMS, folded)
    closed = _hit(_CLOSED_RUBRIC, _subject(area)) if isinstance(area, str) and area.strip() else None
    if contract and closed:
        return "text_clear", closed, contract
    if contract:
        return "kept_contract", contract, None
    return "text_clear", "no_keep_term", None


def decide(docket: str, area: object = None, text: object = None, title: object = None) -> Gate:
    """Keep when the subject decision or the text decision says so.

    ``area`` is the Neuheiten rubric. ``title`` is the ruling's subject line, read only when ``area`` is empty.
    """
    subject, subject_criterion = _subject_decision(docket, area, title)
    text_reason, text_criterion, blocked = _text_decision(text, area_for_gate(area, title))
    kept = subject in _SUBJECT_KEEPS or text_reason in _TEXT_KEEPS
    return Gate(kept, subject, text_reason, subject_criterion, text_criterion, blocked)


def passes(docket: str, area: object = None, text: object = None, title: object = None) -> bool:
    """True when ``decide`` keeps the ruling."""
    return decide(docket, area, text, title).kept


def _path(subject: str, text: str) -> str:
    subject_pass = subject in _SUBJECT_KEEPS
    text_pass = text in _TEXT_KEEPS
    if subject_pass and text_pass:
        return "both"
    if subject_pass:
        return "subject_only"
    if text_pass:
        return "text_only"
    return "dropped"


def gate_record(docket: str, area: object = None, title: object = None, text: object = None) -> dict[str, object]:
    """One layer-1 row. ``text`` is the text decision, not the ruling."""
    gate = decide(docket, area, text, title)
    return {
        "docket": docket,
        "subject": gate.subject,
        "subject_pass": gate.subject in _SUBJECT_KEEPS,
        "subject_criterion": gate.subject_criterion,
        "text": gate.text,
        "text_pass": gate.text in _TEXT_KEEPS,
        "text_criterion": gate.text_criterion,
        "text_blocked_term": gate.text_blocked_term,
        "path": _path(gate.subject, gate.text),
        "kept": gate.kept,
    }



LAYER1_COLUMNS = ["docket", "subject", "text", "apertus", "matter", "in_scope_probability", "kept"]


def layer1_record(
    docket: str, area: object = None, title: object = None, text: object = None, judge: object = None
) -> dict[str, object]:
    """One layer-1 row with the Apertus reading where code could not read the matter.

    ``judge(ruling_text, kept_matters)`` returns ``apertus``, ``matter``, ``in_scope_probability`` and
    ``kept`` (``src/area_judge.gate_judge``). It is called only when ``decide`` says ``needs_apertus``.
    No judge (``pending``) or a failed call (``failed``) keeps the ruling: a missing answer is not a no.
    """
    gate = decide(docket, area, text, title)
    row: dict[str, object] = {
        "docket": docket,
        "subject": gate.subject,
        "text": gate.text,
        "apertus": "not_asked",
        "matter": None,
        "in_scope_probability": None,
        "kept": gate.kept,
    }
    if not gate.needs_apertus:
        return row
    if judge is None:
        row["apertus"] = "pending"
        return row
    try:
        answer = judge(text, AREAS[court_of(docket)[0]])  # type: ignore[operator]
    except Exception:  # noqa: BLE001  any failure of the reading keeps the ruling
        row["apertus"] = "failed"
        return row
    row.update({key: answer[key] for key in ("apertus", "matter", "in_scope_probability", "kept")})
    return row

def _tally(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return counts


def _criteria_present(rows: list[dict], key: str) -> bool:
    return all(isinstance(row[key], str) and row[key].strip() for row in rows)


def _share(count: int, total: int) -> dict[str, int]:
    return {"count": count, "of": total}


def _closed(count: int, parts: dict[str, int]) -> bool:
    return sum(parts.values()) == count


def _asset_view(row: dict) -> dict[str, object]:
    """One asset and the outcome of every action that ran on it."""
    if row["path"] == "dropped":
        deciding = None
    elif row["path"] == "text_only":
        deciding = "layer1.text"
    else:
        deciding = "layer1.subject"
    view = {
        "asset_id": row["docket"],
        "disposition": "kept" if row["kept"] else "dropped",
        "deciding_action": deciding,
        "path": row["path"],
        "actions": [
            {
                "action_id": "layer1.subject",
                "outcome": "pass" if row["subject_pass"] else "fail",
                "reason": row["subject"],
                "criterion": row["subject_criterion"],
            },
            {
                "action_id": "layer1.text",
                "outcome": "pass" if row["text_pass"] else "fail",
                "reason": row["text"],
                "criterion": row["text_criterion"],
                "blocked_term": row["text_blocked_term"],
                "in_rescue_scope": not row["subject_pass"],
            },
        ],
    }
    for key in ("cohort", "quarter", "rubric"):
        if key in row:
            view[key] = row[key]
    return view


def _duplicates(records: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for row in records:
        counts[row["docket"]] = counts.get(row["docket"], 0) + 1
    return [{"asset_id": docket, "rows": n} for docket, n in sorted(counts.items()) if n > 1]


def build_layer1_log(records: list[dict], run: dict) -> dict:
    """Audit log of one filter run. Every action states its population and its checks."""
    total = len(records)
    passed_subject = [row for row in records if row["subject_pass"]]
    failed_subject = [row for row in records if not row["subject_pass"]]
    rescued = [row for row in failed_subject if row["text_pass"]]
    still_out = [row for row in failed_subject if not row["text_pass"]]
    kept = [row for row in records if row["kept"]]
    dropped = [row for row in records if not row["kept"]]
    passed_by = _tally(passed_subject, "subject")
    dropped_subject_by = _tally(failed_subject, "subject")
    passed_subject_by_criterion = _tally(passed_subject, "subject_criterion")
    dropped_subject_by_criterion = _tally(failed_subject, "subject_criterion")
    rescued_by = _tally(rescued, "text")
    still_by = _tally(still_out, "text")
    outside_by = _tally(passed_subject, "text")
    rescued_by_criterion = _tally(rescued, "text_criterion")
    still_by_criterion = _tally(still_out, "text_criterion")
    outside_by_criterion = _tally(passed_subject, "text_criterion")
    by_path = _tally(kept, "path")
    subject_checks = {
        "in_equals_out_plus_dropped": total == len(passed_subject) + len(failed_subject),
        "passed_reasons_sum_to_out": _closed(len(passed_subject), passed_by),
        "dropped_reasons_sum_to_dropped": _closed(len(failed_subject), dropped_subject_by),
        "passed_criteria_sum_to_out": _closed(len(passed_subject), passed_subject_by_criterion),
        "dropped_criteria_sum_to_dropped": _closed(len(failed_subject), dropped_subject_by_criterion),
        "every_criterion_present": _criteria_present(records, "subject_criterion"),
    }
    text_checks = {
        "scope_equals_subject_failures": len(failed_subject) == len(rescued) + len(still_out),
        "passed_reasons_sum_to_out": _closed(len(rescued), rescued_by),
        "dropped_reasons_sum_to_dropped": _closed(len(still_out), still_by),
        "outside_scope_sums_to_subject_passes": _closed(len(passed_subject), outside_by),
        "passed_criteria_sum_to_out": _closed(len(rescued), rescued_by_criterion),
        "dropped_criteria_sum_to_dropped": _closed(len(still_out), still_by_criterion),
        "outside_scope_criteria_sum": _closed(len(passed_subject), outside_by_criterion),
        "every_criterion_present": _criteria_present(records, "text_criterion"),
        "evaluated_on_every_asset": True,
    }
    disposition_checks = {
        "in_equals_out_plus_dropped": total == len(kept) + len(dropped),
        "out_equals_subject_passes_plus_text_rescues": len(kept) == len(passed_subject) + len(rescued),
        "dropped_equals_text_failures": len(dropped) == len(still_out),
        "paths_sum_to_out": _closed(len(kept), by_path),
    }
    actions = [
        {
            "sequence": 1,
            "action_id": "layer1.subject",
            "kind": "filter",
            "applies_to": "all_assets",
            "rule": {
                "keeps_when": ["kept_subject", "subject_missing"],
                "drops_when": ["wrong_court", "wrong_letter", "subject_out"],
            },
            "assets_in": total,
            "assets_out": len(passed_subject),
            "assets_dropped": len(failed_subject),
            "keep": _share(len(passed_subject), total),
            "drop": _share(len(failed_subject), total),
            "passed_by_reason": passed_by,
            "dropped_by_reason": dropped_subject_by,
            "passed_by_criterion": passed_subject_by_criterion,
            "dropped_by_criterion": dropped_subject_by_criterion,
            "checks": subject_checks,
        },
        {
            "sequence": 2,
            "action_id": "layer1.text",
            "kind": "filter",
            "applies_to": "assets_failed_by_layer1.subject",
            "parent_action": "layer1.subject",
            "rule": {
                "keeps_when": ["kept_text", "kept_contract"],
                "drops_when": ["text_clear", "text_absent"],
            },
            "assets_in_scope": len(failed_subject),
            "assets_out": len(rescued),
            "assets_dropped": len(still_out),
            "keep": _share(len(rescued), len(failed_subject)),
            "drop": _share(len(still_out), len(failed_subject)),
            "passed_by_reason": rescued_by,
            "dropped_by_reason": still_by,
            "passed_by_criterion": rescued_by_criterion,
            "dropped_by_criterion": still_by_criterion,
            "outside_scope": len(passed_subject),
            "outside_scope_by_reason": outside_by,
            "outside_scope_by_criterion": outside_by_criterion,
            "checks": text_checks,
        },
        {
            "sequence": 3,
            "action_id": "layer1.disposition",
            "kind": "combine",
            "applies_to": "all_assets",
            "rule": "kept when layer1.subject passed or layer1.text passed",
            "assets_in": total,
            "assets_out": len(kept),
            "assets_dropped": len(dropped),
            "keep": _share(len(kept), total),
            "drop": _share(len(dropped), total),
            "passed_by_path": by_path,
            "checks": disposition_checks,
        },
    ]
    check_values = [ok for action in actions for ok in action["checks"].values()]
    assets = [_asset_view(row) for row in records]
    kept_assets = sum(1 for asset in assets if asset["disposition"] == "kept")
    duplicates = _duplicates(records)
    quality_checks = {
        "asset_rows_equal_assets_in": len(assets) == total,
        "kept_assets_equal_assets_out": kept_assets == len(kept),
        "every_action_check_passed": all(check_values),
    }
    return {
        "schema_version": "layer1-log-1",
        "phase": run["phase"],
        "phase_kind": "filter",
        "run": run,
        "population": {
            "unit": "ruling",
            "assets_in": total,
            "assets_out": len(kept),
            "assets_dropped": len(dropped),
            "keep": _share(len(kept), total),
            "drop": _share(len(dropped), total),
        },
        "actions": actions,
        "quality": {
            "all_checks_passed": all(quality_checks.values()),
            "checks": quality_checks,
            "distinct_asset_ids": len({row["docket"] for row in records}),
            "duplicate_asset_ids": duplicates,
        },
        "assets": assets,
    }


# One batch of ruling texts in memory. The cache is not loaded whole.
BATCH = 256


def _filled(value):
    return value if isinstance(value, str) and value.strip() else None


def write_layer1(cache, dest, limit: int | None = None, batch_size: int = BATCH):
    """Write the layer-1 log for ``cache``. The ruling text is not stored.

    Reads ``batch_size`` rows at a time, so the texts of the whole cache are
    not held together. ``dest`` is the JSON log.
    """
    import hashlib
    from datetime import datetime
    from uuid import uuid4

    import pyarrow.parquet as pq

    started = datetime.now(UTC)
    seen = 0
    kept_n = 0
    records: list[dict] = []
    source = pq.ParquetFile(cache)
    for batch in source.iter_batches(batch_size=batch_size, columns=["docket", "area", "subject", "text"]):
        data = batch.to_pydict()
        for i, docket in enumerate(data["docket"]):
            if limit is not None and seen >= limit:
                break
            seen += 1
            text = data["text"][i]
            record = gate_record(
                docket,
                _filled(data["area"][i]),
                _filled(data["subject"][i]),
                text if isinstance(text, str) else None,
            )
            kept_n += int(bool(record["kept"]))
            records.append(record)
        if limit is not None and seen >= limit:
            break
    finished = datetime.now(UTC)
    digest = hashlib.sha256()
    with open(cache, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    _write_json(
        dest,
        build_layer1_log(
            records,
            {
                "run_id": str(uuid4()),
                "phase": "layer1",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "selection": "all" if limit is None else limit,
                "batch_size": batch_size,
                "code": "src/courts.py",
                "input": {
                    "path": str(cache),
                    "format": "parquet",
                    "bytes": cache.stat().st_size,
                    "sha256": digest.hexdigest(),
                    "rows_read": seen,
                },
                "output": {"log": str(dest)},
            },
        ),
    )
    return seen, kept_n


def _self_check() -> None:
    assert passes("8C_78/2025", "Unfallversicherung")
    assert passes("9C_65/2025", "Assicurazione per l'invalidità")
    assert passes("4A_106/2025", "Vertragsrecht")
    assert passes("4A_106/2025", "Vertragsrecht*")
    assert passes("8F_1/2025", "Assurance-accidents")
    assert passes("9C_1/2025", "Assurance-maladie")
    assert passes("9D_1/2025", "Prévoyance professionnelle")
    assert not passes("8C_748/2024", "Arbeitslosenversicherung")
    assert not passes("7B_1/2025", "Unfallversicherung")
    assert not passes("9C_1/2025", "Finances publiques & droit fiscal")
    assert passes("8C_1/2025", "Militärversicherung")
    assert passes("4A_1/2025", "Haftpflichtrecht")
    assert passes("4A_1/2025", "Assurance responsabilité civile")
    assert not passes("4A_1/2025", "Schuldbetreibungs- und Konkursrecht")
    assert passes("8C_1/2025", None)
    assert not passes("5A_1/2025", "Droit des contrats")
    blank = decide("8C_1/2025", None)
    assert blank.kept and blank.subject == "subject_missing" and blank.text == "text_absent"
    assert decide("8C_1/2025", "   ").subject == "subject_missing"
    assert decide("7B_1/2025", None).subject == "wrong_court"
    assert decide("4B_1/2025", "Vertragsrecht").subject == "wrong_letter"
    dropped = decide("8C_748/2024", "Arbeitslosenversicherung", "Le recours est rejeté.")
    assert not dropped.kept and dropped.subject == "subject_out" and dropped.text == "text_clear"
    kept_by_text = decide("8C_748/2024", "Arbeitslosenversicherung", "La CNA est intimée.")
    assert kept_by_text.kept and kept_by_text.subject == "subject_out" and kept_by_text.text == "kept_text"
    assert decide("6B_1/2025", "Droit pénal", "Art. 6 UVG.").text == "kept_text"
    contract = decide("4A_1/2025", "Obligationenrecht (allgemein)", "Art. 14 Abs. 2 VVG.")
    assert contract.kept and contract.subject == "subject_out" and contract.text == "kept_contract"
    daily = decide("4A_2/2025", "Gesellschaftsrecht", "Die Taggeldversicherung deckt den Ausfall.")
    assert daily.kept and daily.text == "kept_contract"
    assert decide("7B_1/2025", "Procédure pénale", "art. 95c LCA (RS 221.229.1)").text == "kept_contract"
    bare = decide("8C_748/2024", "Arbeitslosenversicherung", "Das Taggeld wird gekürzt.")
    assert not bare.kept and bare.text == "text_clear"
    closed = decide("8C_748/2024", "Arbeitslosenversicherung", "Art. 14 Abs. 2 VVG.")
    assert not closed.kept and closed.text == "text_clear"
    french_unemployment = decide("8C_1/2025", "Assurance-chômage", "les indemnités journalières sont réduites")
    assert not french_unemployment.kept and french_unemployment.text == "text_clear"
    row = gate_record("9C_1/2025", None, "Berufliche Vorsorge,", None)
    assert row == {
        "docket": "9C_1/2025",
        "subject": "kept_subject",
        "subject_pass": True,
        "subject_criterion": "berufliche vorsorge",
        "text": "text_absent",
        "text_pass": False,
        "text_criterion": "empty_text",
        "text_blocked_term": None,
        "path": "subject_only",
        "kept": True,
    }
    assert kept_by_text.subject_criterion == "arbeitslosenversicherung"
    assert kept_by_text.text_criterion == "cna" and kept_by_text.text_blocked_term is None
    assert contract.text_criterion == "vvg"
    assert closed.text_criterion == "arbeitslos" and closed.text_blocked_term == "vvg"
    assert bare.text_criterion == "no_keep_term" and bare.text_blocked_term is None
    assert blank.subject_criterion == "blank_rubric" and blank.text_criterion == "empty_text"
    assert decide("7B_1/2025", None).subject_criterion == "7"
    assert decide("4B_1/2025", "Vertragsrecht").subject_criterion == "B"
    print("filter ok")


def _first_rulings(path, dockets: set[str], batch_size: int = BATCH) -> dict[str, tuple]:
    """First cache row of each docket. Stops once every requested docket is found."""
    import pyarrow.parquet as pq

    found: dict[str, tuple] = {}
    remaining = set(dockets)
    if not remaining:
        return found
    source = pq.ParquetFile(path)
    columns = ["docket", "area", "subject", "text", "decision_quarter"]
    for batch in source.iter_batches(batch_size=batch_size, columns=columns):
        data = batch.to_pydict()
        for i, docket in enumerate(data["docket"]):
            if docket not in remaining:
                continue
            found[docket] = (data["area"][i], data["subject"][i], data["text"][i], data["decision_quarter"][i])
            remaining.remove(docket)
        if not remaining:
            break
    return found


def _rows(path, columns: list[str]) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path, columns=columns).to_pylist()


def _unique(rows: list[dict], key: str) -> list[dict]:
    seen: set[str] = set()
    out = []
    for row in rows:
        if row[key] in seen:
            continue
        seen.add(row[key])
        out.append(row)
    return out


def _on(value) -> str:
    """Calendar day as ``YYYY-MM-DD``. Parquet may store a date or a timestamp."""
    return str(value)[:10]


def write_recall(cache_dir, dest):
    """Score the Suva list and the Q3/2025 summaries. No ruling text is stored.

    Reads docket, quarter and decision date from the label table, and docket
    plus decision date from the summary table. The intranet link and the
    author column are not read. The ruling file is scanned in batches, and
    only the rows of these cohorts are kept.
    """
    from datetime import datetime

    started = datetime.now(UTC)
    listed = _unique(_rows(cache_dir / "labels.parquet", ["docket", "quarter", "decision_date"]), "docket")
    gold = _rows(cache_dir / "gold_summaries.parquet", ["docket", "decision_date", "is_current"])
    summaries = _unique([row for row in gold if row["is_current"]], "docket")
    listed_dockets = {row["docket"] for row in listed}
    q3 = [
        row
        for row in summaries
        if "2025-07-01" <= _on(row["decision_date"]) <= "2025-09-30" and row["docket"] not in listed_dockets
    ]
    by_docket = _first_rulings(cache_dir / "rulings.parquet", listed_dockets | {row["docket"] for row in q3})
    rows = []
    for cohort, frame, quarter_col in (
        ("suva_list", listed, "quarter"),
        ("q3_summary", q3, None),
    ):
        for item in frame:
            docket = item["docket"]
            if docket not in by_docket:
                rows.append(
                    {
                        "docket": docket,
                        "cohort": cohort,
                        "quarter": item[quarter_col] if quarter_col else "",
                        "rubric": "",
                        "subject": "missing_ruling",
                        "subject_pass": False,
                        "subject_criterion": "missing_from_cache",
                        "text": "text_absent",
                        "text_pass": False,
                        "text_criterion": "empty_text",
                        "text_blocked_term": None,
                        "path": "dropped",
                        "kept": False,
                    }
                )
                continue
            ruling = by_docket[docket]
            text = ruling[2]
            filled = area_for_gate(_filled(ruling[0]), _filled(ruling[1]))
            gate = decide(docket, filled, text if isinstance(text, str) else None)
            quarter = item[quarter_col] if quarter_col else ruling[3]
            rows.append(
                {
                    "docket": docket,
                    "cohort": cohort,
                    "quarter": quarter or "",
                    "rubric": filled if isinstance(filled, str) else "",
                    "subject": gate.subject,
                    "subject_pass": gate.subject in _SUBJECT_KEEPS,
                    "subject_criterion": gate.subject_criterion,
                    "text": gate.text,
                    "text_pass": gate.text in _TEXT_KEEPS,
                    "text_criterion": gate.text_criterion,
                    "text_blocked_term": gate.text_blocked_term,
                    "path": _path(gate.subject, gate.text),
                    "kept": gate.kept,
                }
            )
    import hashlib
    from uuid import uuid4

    by_cohort = []
    for cohort in ("suva_list", "q3_summary"):
        part = [row for row in rows if row["cohort"] == cohort]
        by_cohort.append(
            {
                "cohort": cohort,
                "assets_in": len(part),
                "assets_out": sum(1 for row in part if row["kept"]),
                "assets_dropped": sum(1 for row in part if not row["kept"]),
            }
        )
    finished = datetime.now(UTC)
    source = cache_dir / "rulings.parquet"
    digest = hashlib.sha256()
    with open(source, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    log = build_layer1_log(
        rows,
        {
            "run_id": str(uuid4()),
            "phase": "layer1_recall",
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "selection": "known_positives",
            "batch_size": BATCH,
            "code": "src/courts.py",
            "input": {
                "path": str(source),
                "format": "parquet",
                "bytes": source.stat().st_size,
                "sha256": digest.hexdigest(),
                "rows_read": len(rows),
            },
            "output": {"log": str(dest)},
        },
    )
    log["phase"] = "layer1_recall"
    log["phase_kind"] = "recall_check"
    log["quality"]["by_cohort"] = by_cohort
    _write_json(dest, log)
    return rows


def _write_json(path, payload) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Write data/cache/layer1.json. Pass ``--limit N`` or ``--all``."""
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Write the layer-1 table for the local cache.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recall", action="store_true", help="Score the Suva list and the Q3/2025 summaries.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.recall:
        cache_dir = root / "data" / "cache"
        dest = root / "data" / "derived" / "layer1_recall.json"
        needed = [cache_dir / "rulings.parquet", cache_dir / "labels.parquet", cache_dir / "gold_summaries.parquet"]
        missing = [str(path) for path in needed if not path.exists()]
        if missing:
            print("recall needs " + ", ".join(missing), file=sys.stderr)
            return 2
        out = write_recall(cache_dir, dest)
        failed = sum(1 for row in out if not row["kept"])
        for cohort in ("suva_list", "q3_summary"):
            part = [row for row in out if row["cohort"] == cohort]
            print(f"{cohort}: {sum(1 for row in part if row['kept'])}/{len(part)} kept")
        print(f"wrote {dest} ({len(out)} rows, {failed} dropped)")
        return 1 if failed else 0
    if not args.all and args.limit is None:
        print("pass --limit N or --all", file=sys.stderr)
        return 2
    cache = root / "data" / "cache" / "rulings.parquet"
    dest = root / "data" / "cache" / "layer1.json"
    if args.dry_run:
        print(f"dry-run: would write {dest} from {cache} ({args.limit or 'all'} rows)")
        return 0
    rows, kept = write_layer1(cache, dest, None if args.all else args.limit)
    print(f"wrote {dest} ({rows} rows, {kept} kept)")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        _self_check()
    else:
        raise SystemExit(main())

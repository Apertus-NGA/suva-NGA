"""Run layer 1 over the corpus: files first, then the database (D-061, D-073; docs/LAYER1.md §6).

1. The run reads the `layer1_filter` version its profile pins, with its configuration and rules (D-064).
2. It decides every ruling, evaluating every rule of the version (the ledger, F-01), and checks each decision
   against the frozen reference `src/layer1/reference_courts_4c246a8.py` (parity count): a byte-identical copy of
   `src/courts.py` at 4c246a8, the code V1.0.0 reproduces (D-073), so parity never moves with the live
   `src/courts.py`, which its owner keeps changing (L2-F21).
3. When it covers the whole corpus loaded from the pinned snapshot of `expected/layer1/<version>.json`, it compares
   its decisions with that certified file (`src.layer1.golden`): a difference fails the run (F-09 follow-up, §2.4).
4. It writes `data/runs/<run_id>/`: `decisions.jsonl` (one Layer1DecisionRecord per ruling, with every rule
   evaluation), `layer1_log.json` (the `layer1-log-1` contract of docs/layer1_log.schema.json, built by
   `build_layer1_log` of the frozen reference, with its closure checks, timestamps and input fingerprint) and
   `manifest.json` (counts, parity reference, golden status and SHA-256 of both files).
5. It loads the same records into the database in one transaction: one span, one assessment and one ledger row
   per rule of the version per ruling (with evidence), events and metrics. The database certifies each row and,
   at commit, each complete ledger (triggers t30_check, t50_ledger). Nothing is written if any row fails.

`verify_run` re-reads the files of a run and proves they equal its database rows (F-16).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from pydantic import ValidationError

from src.db.pg import ROOT, sha256_file, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import Run, begin_run, events, fail_run, finish_run, metrics
from src.layer1 import golden
from src.layer1 import reference_courts_4c246a8 as reference
from src.layer1.engine import Decision, Layer1Engine, RuleSpec, fingerprint
from src.layer1.models import Layer1Config, Layer1DecisionRecord, RuleEvaluation

STEP = "layer1_filter"
# The parity reference: `git show 4c246a8:src/courts.py`, byte for byte, never edited (tests/test_layer1_reference.py).
REFERENCE_PATH = "src/layer1/reference_courts_4c246a8.py"
REFERENCE_SOURCE = "src/courts.py@4c246a8"
# The code a layer-1 run executes, recorded per run (params.code_sha256, F-09).
CODE_PATHS = tuple(
    f"src/layer1/{name}.py" for name in ("engine", "models", "run", "golden", "recall", "reference_courts_4c246a8")
)
OUTCOMES = ("fired", "not_fired", "not_applicable", "blocked")
_SUBJECT_RULES = frozenset(
    {"L1_KEEP_RUBRIC", "L1_KEEP_RUBRIC_MISSING", "L1_DROP_WRONG_COURT", "L1_DROP_WRONG_LETTER", "L1_DROP_RUBRIC_OUT"}
)
_TITLE_RUBRIC_RULE, _TEXT_UNAVAILABLE_RULE = "L1_KEEP_TITLE_RUBRIC", "L1_KEEP_TEXT_UNAVAILABLE"  # V1.2.0 (D-083)
NO_TEXT = "Kein Urteilstext verfügbar: die Begriffsprüfung war nicht möglich."
# What a text keep rule that did not fire searched: the term list of its version (detail.pattern), never what the
# ruling is about. A rule's label states a meaning ("Text nennt die Suva ..."); a ruling can name Suva or accident
# insurance in a wording the list lacks, so a drop explanation names the lists searched and says so.
TERM_LISTS = {
    "accident_terms": "Suchbegriffe zu Suva, Unfall- und Militärversicherung",
    "contract_terms": "Suchbegriffe zu VVG und Taggeldversicherung",
}
SEARCH_SCOPE = "nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht"
RUNS_DIR = ROOT / "data" / "runs"
_RULINGS_SQL = """
SELECT r.ruling_id::text, r.docket, r.decision_date::text, r.gegenstand, t.text_id::text, t.content, t.content_sha256,
       (SELECT s.rubric FROM corpus.subject_observation s WHERE s.ruling_id = r.ruling_id AND s.source = 'neuheiten'),
       (SELECT s.rubric FROM corpus.subject_observation s WHERE s.ruling_id = r.ruling_id AND s.source =
           'hf_legal_area')
FROM corpus.ruling r
LEFT JOIN corpus.ruling_text t ON t.ruling_id = r.ruling_id AND t.is_primary
{where}
ORDER BY r.docket, r.decision_date
"""


def load_version(
    cur: psycopg.Cursor, component_version_id: str
) -> tuple[Layer1Config, list[RuleSpec], dict[str, str], str]:
    cur.execute(
        "SELECT config, version_label FROM ops.component_version WHERE component_version_id = %s AND step = %s",
        (component_version_id, STEP),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"{component_version_id} is not a {STEP} version")
    config = Layer1Config.model_validate(row[0])
    cur.execute(
        """SELECT r.rule_code, r.definition ->> 'check', r.kind::text, cvr.ordinal, r.rule_id::text, r.reason_code
           FROM ops.component_version_rule cvr JOIN ops.rule r ON r.rule_id = cvr.rule_id
           WHERE cvr.component_version_id = %s AND cvr.enabled ORDER BY cvr.ordinal""",
        (component_version_id,),
    )
    found = cur.fetchall()
    renamed = sorted(code for code, *_, reason in found if reason != code)
    if renamed:  # the engine reports a rule's code as its reason code; the ledger trigger checks the reason code
        raise ValueError(f"{STEP} rules whose reason code is not their rule code: {renamed}")
    rules = [RuleSpec(code, check, kind, ordinal) for code, check, kind, ordinal, _, _ in found]
    return config, rules, {code: rid for code, _, _, _, rid, _ in found}, row[1]


def explain(decision: Decision, labels: dict[str, str]) -> str:
    """The German reason a lawyer reads (G5), composed from the ledger of the decision."""
    return compose_explanation(decision.kept, decision.reason_code, decision.evaluations, labels)


def compose_explanation(
    kept: bool, reason_code: str, evaluations: tuple[RuleEvaluation, ...] | list[RuleEvaluation], labels: dict[str, str]
) -> str:
    """Kept: the decisive keep, then the other fired keeps. Dropped: the decisive drop, then what the text check
    found (F-03): no text, the term lists searched without a match (named as lists, never as a claim about what the
    ruling says), a term found but blocked (F-02). Then the title signal when the rubric was read from the title."""
    fired = [e for e in evaluations if e.outcome == "fired"]
    if kept:
        text = f"Vorauswahl bestanden: {labels[reason_code]}."
        others = sorted({e.rule_code for e in fired if e.effect == "keep" and e.rule_code != reason_code})
        if others:
            text += " Ebenso: " + "; ".join(labels[c] for c in others) + "."
    else:
        text = f"Von der Vorauswahl ausgeschlossen: {labels[reason_code]}."
        if any(e.outcome == "not_applicable" and e.detail.get("why") == "text_absent" for e in evaluations):
            text += " " + NO_TEXT
        searched = [
            str(e.detail["pattern"])
            for e in evaluations
            if e.effect == "keep"
            and e.outcome == "not_fired"
            and e.evidence_field == "full_text"
            and e.detail.get("pattern")
        ]
        if searched:
            lists = "; ".join(TERM_LISTS.get(p, f"Begriffsliste «{p}»") for p in searched)
            text += f" Im Urteilstext geprüft, ohne Treffer: {lists} ({SEARCH_SCOPE})."
        by_code = {e.rule_code: e for e in evaluations}
        blocked = [e for e in evaluations if e.outcome == "blocked"]
        blockers = {str(e.detail["blocked_by"]) for e in blocked}
        for e in blocked:  # the term found, the rule that blocked it and the rubric it read
            code = str(e.detail["blocked_by"])
            rubric = (by_code[code].examined_value if code in by_code else None) or e.detail["closed_rubric_match"]
            text += f" Hinweis: {labels[code]}: «{e.matched_text}» im Urteilstext gefunden, Rechtsgebiet «{rubric}»."
        flags = sorted({e.rule_code for e in fired if e.effect == "flag" and e.rule_code not in blockers})
        if flags:
            text += " Hinweis: " + "; ".join(labels[c] for c in flags) + "."
    for e in fired:
        if e.effect == "signal" and e.evidence_field == "gegenstand" and e.matched_text:
            text += f" ({labels.get(e.rule_code, 'Rechtsgebiet aus dem Gegenstand')}: {e.matched_text})"
    return text


def _reference_row(docket: str, rubric_fields: dict[str, str | None], gegenstand: str | None, text: str | None) -> dict:
    """The decision of the frozen reference (src/courts.py at 4c246a8) on the same inputs (its `area` is the first
    filled rubric field)."""
    area = rubric_fields.get("neuheiten") or rubric_fields.get("hf_legal_area")
    return reference.gate_record(docket, area, gegenstand, text)


def _log_row(ref: dict, decision: Decision) -> dict:
    """A `layer1-log-1` row for a decision that differs from the reference: reasons and criteria from the rule hits.

    The log keeps a ruling when its subject action or its text action passes (its closure checks fail the run
    otherwise). A V1.2.0 keep the reference does not know (D-083) passes the action it belongs to: the title rubric
    is a subject pass (`kept_title_rubric`, criterion = the cut title head), the missing text a text pass
    (`kept_text_unavailable`, criterion `empty_text`)."""
    subject_hit = next(h for h in decision.hits if h.rule_code in _SUBJECT_RULES)
    title_hit = next((h for h in decision.hits if h.rule_code == _TITLE_RUBRIC_RULE), None)
    no_text = any(h.rule_code == _TEXT_UNAVAILABLE_RULE for h in decision.hits)
    text_hit = next(
        (
            h
            for h in decision.hits
            if h.effect == "keep" and h.evidence.field == "full_text" and h.rule_code != _TEXT_UNAVAILABLE_RULE
        ),
        None,
    )
    blocked = next((e for e in decision.evaluations if e.outcome == "blocked"), None)
    if text_hit is not None:
        text_criterion = text_hit.evidence.matched.casefold()
    elif blocked is not None:
        text_criterion = str(blocked.detail["closed_rubric_match"])
    else:
        text_criterion = "empty_text" if decision.text == "text_absent" else "no_keep_term"
    subject, subject_criterion = decision.subject, subject_hit.evidence.matched.casefold()
    subject_pass = decision.subject in ("kept_subject", "subject_missing")
    if not subject_pass and title_hit is not None:
        subject, subject_pass, subject_criterion = "kept_title_rubric", True, title_hit.evidence.matched.casefold()
    text, text_pass = decision.text, decision.text in ("kept_text", "kept_contract")
    if not text_pass and no_text:
        text, text_pass = "kept_text_unavailable", True
    paths = {(True, True): "both", (True, False): "subject_only", (False, True): "text_only"}
    return ref | {
        "subject": subject,
        "subject_pass": subject_pass,
        "subject_criterion": subject_criterion,
        "text": text,
        "text_pass": text_pass,
        "text_criterion": text_criterion,
        "text_blocked_term": blocked.matched_text.casefold() if blocked is not None else None,
        "path": paths.get((subject_pass, text_pass), "dropped"),
        "kept": decision.kept,
    }


def _write(run_dir: Path, records: list[Layer1DecisionRecord], log: dict, manifest: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    decisions = run_dir / "decisions.jsonl"
    with decisions.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(rec.model_dump_json() + "\n")
    log_path = run_dir / "layer1_log.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["files"] = {p.name: sha256_file(p) for p in (decisions, log_path)}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _outcomes(evaluations: list[RuleEvaluation] | tuple[RuleEvaluation, ...]) -> dict[str, int]:
    counts = Counter(e.outcome for e in evaluations)
    return {o: counts[o] for o in OUTCOMES}


def _load(cur: psycopg.Cursor, run: Run, records: list[Layer1DecisionRecord], rule_ids: dict[str, str]) -> None:
    """Spans, assessments and the full rule ledger of every ruling (deterministic ids). The ledger of an
    assessment is sealed when its transaction commits: loading a committed run again is refused by the database."""
    spans, assessments, reasons, evts = [], [], [], []
    for seq, rec in enumerate(records, start=10):
        span_id = uuid5(f"span|{run.run_id}|{rec.ruling_id}|{STEP}")
        assessment_id = uuid5(f"assessment|{run.run_id}|{rec.ruling_id}|{STEP}|0")
        spans.append(
            (
                span_id,
                run.run_id,
                run.span_id,
                rec.ruling_id,
                run.component_version_id,
                json.dumps({"subject": rec.subject, "text": rec.text, "outcomes": _outcomes(rec.evaluations)}),
            )
        )
        dropped = rec.in_suva_scope == "out_of_scope"
        assessments.append(
            (
                assessment_id,
                run.run_id,
                rec.ruling_id,
                run.component_version_id,
                span_id,
                rec.text_id,
                rec.input_fingerprint,
                rec.in_suva_scope,
                0.0 if dropped else None,
                rec.score_0_100,
                "net" if dropped else None,
                rec.reason_code,
                rec.explanation_de,
            )
        )
        for ev in rec.evaluations:
            reasons.append(
                (
                    assessment_id,
                    ev.ordinal,
                    rule_ids[ev.rule_code],
                    ev.rule_code,
                    ev.effect,
                    ev.outcome,
                    ev.evidence_field,
                    ev.examined_value,
                    ev.char_start,
                    ev.char_end,
                    ev.matched_text,
                    json.dumps(ev.detail, ensure_ascii=False),
                )
            )
        evts.append(
            (
                seq,
                "info",
                "layer1.decision.made",
                rec.reason_code,
                {"in_suva_scope": rec.in_suva_scope, "subject": rec.subject, "text": rec.text},
                rec.ruling_id,
                span_id,
            )
        )
    cur.executemany(
        """INSERT INTO ops.span (span_id, run_id, parent_span_id, step, operation, ruling_id, component_version_id,
                                 status, started_at, ended_at, attributes)
           VALUES (%s, %s, %s, 'layer1_filter', 'layer1.decide', %s, %s, 'ok', now(), now(), %s)
           ON CONFLICT DO NOTHING""",
        spans,
    )
    cur.executemany(
        """INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id,
                                          input_text_id, input_fingerprint, in_suva_scope, outcome, score_raw,
                                          score_0_100, score_source, reason_code, explanation_de, mode, started_at,
                                          finished_at)
           VALUES (%s, %s, %s, 'layer1_filter', %s, %s, %s, %s, %s, 'ok', %s, %s, %s, %s, %s, 'LIVE', now(), now())
           ON CONFLICT DO NOTHING""",
        assessments,
    )
    cur.executemany(
        """INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome,
                                                 evidence_field, examined_value, char_start, char_end, matched_text,
                                                 detail)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        reasons,
    )
    events(cur, run, STEP, evts)


def _golden(
    cur: psycopg.Cursor, version: str, population: str | None, lines: list[str], kept: int, by_reason: Counter
) -> dict:
    """Golden status of this run against expected/layer1/<version>.json (§2.4): matched, mismatch or not_comparable."""
    stored = golden.expected_layer1(version)
    pinned, ingest_versions = False, set()
    if stored is not None and population is None:
        snap = stored["snapshot"]
        cur.execute(
            """SELECT EXISTS (SELECT 1 FROM ops.source_snapshot
                              WHERE source = 'hf_bger' AND file_sha256 = %s AND revision = %s)""",
            (snap["file_sha256"], snap["hf_revision"]),
        )
        pinned = cur.fetchone()[0]
        cur.execute(
            """SELECT DISTINCT cv.version_label FROM corpus.ruling r
               JOIN ops.span s ON s.run_id = r.created_by_run_id AND s.parent_span_id IS NULL
               JOIN ops.component_version cv ON cv.component_version_id = s.component_version_id
               WHERE cv.step = 'ingest'"""
        )
        ingest_versions = {row[0] for row in cur.fetchall()}
    return golden.compare_run(
        stored,
        population=population,
        snapshot_pinned=pinned,
        ingest_versions=ingest_versions,
        lines=lines,
        kept=kept,
        by_reason=dict(by_reason),
    )


def run_layer1(
    conn: psycopg.Connection,
    *,
    profile: str = "default",
    population: str | None = None,
    runs_dir: Path = RUNS_DIR,
    actor: str = "pipeline",
) -> dict:
    with conn.cursor() as cur:
        pvid, profile_label = profile_version(cur, profile)
        cvid = pinned_version(cur, pvid, STEP)
        config, rules, rule_ids, version = load_version(cur, cvid)
        cur.execute("SELECT code, label_de FROM ops.reason_code")
        labels = dict(cur.fetchall())
    engine = Layer1Engine(config, rules)
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="layer1",
        step=STEP,
        operation="layer1.run",
        component_version_id=cvid,
        params={"profile": profile, "profile_version": profile_label, "version": version, "population": population},
        code_paths=CODE_PATHS,
        actor=actor,
    )
    try:
        where, args = "", ()
        if population:
            where = (
                "WHERE EXISTS (SELECT 1 FROM corpus.population_member m"
                " JOIN corpus.population p ON p.population_id = m.population_id"
                " WHERE m.ruling_id = r.ruling_id AND p.code = %s)"
            )
            args = (population,)
        records: list[Layer1DecisionRecord] = []
        log_rows: list[dict] = []
        lines: list[str] = []
        parity = Counter()
        mismatches: list[str] = []
        text_bytes = 0
        started = datetime.now(UTC)
        with conn.cursor(name="layer1_rulings") as cur:
            cur.itersize = 500
            cur.execute(_RULINGS_SQL.format(where=where), args)
            for ruling_id, docket, decided, gegenstand, text_id, text, text_sha, neuheiten, legal_area in cur:
                rubric_fields = {"neuheiten": neuheiten, "hf_legal_area": legal_area}
                decision = engine.decide(docket, rubric_fields, gegenstand, text)
                ref = _reference_row(docket, rubric_fields, gegenstand, text)
                same = (ref["kept"], ref["subject"], ref["text"]) == (
                    decision.kept,
                    decision.subject,
                    decision.text,
                )
                parity["same" if same else "different"] += 1
                if not same and len(mismatches) < 50:
                    mismatches.append(docket)
                log_rows.append(ref if same else _log_row(ref, decision))
                lines.append(golden.canonical_line(docket, decided, decision))
                text_bytes += len(text.encode("utf-8")) if isinstance(text, str) else 0
                records.append(
                    Layer1DecisionRecord(
                        run_id=run.run_id,
                        ruling_id=ruling_id,
                        docket=docket,
                        decision_date=decided,
                        text_id=text_id,
                        input_fingerprint=fingerprint(cvid, docket, decided, rubric_fields, gegenstand, text_sha),
                        in_suva_scope=decision.in_suva_scope,
                        reason_code=decision.reason_code,
                        score_0_100=decision.score_0_100,
                        rubric=decision.rubric,
                        rubric_source=decision.rubric_source,
                        subject=decision.subject,
                        text=decision.text,
                        evaluations=list(decision.evaluations),
                        explanation_de=explain(decision, labels),
                    )
                )
        finished = datetime.now(UTC)
        conn.commit()  # close the named cursor's transaction
        if not records:
            raise RuntimeError("layer 1 read 0 rulings: load the base dataset first (G6: a step with 0 output fails)")
        kept = sum(1 for r in records if r.in_suva_scope == "potentially")
        by_reason = Counter(r.reason_code for r in records)
        outcomes = Counter(e.outcome for r in records for e in r.evaluations)
        with conn.cursor() as cur:
            golden_result = _golden(cur, version, population, lines, kept, by_reason)
        conn.commit()
        parity_reference = {
            "path": REFERENCE_PATH,
            "source": REFERENCE_SOURCE,
            "sha256": sha256_file(ROOT / REFERENCE_PATH),
        }
        input_sha = hashlib.sha256("\n".join(sorted(r.input_fingerprint for r in records)).encode()).hexdigest()
        log = reference.build_layer1_log(
            log_rows,
            {
                "run_id": run.run_id,
                "phase": "layer1",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "selection": population or "all",
                "batch_size": 500,
                "code": f"src/layer1/engine.py ({STEP} {version})",
                "input": {
                    "path": "postgresql: corpus.ruling",
                    "format": "database",
                    "bytes": text_bytes,
                    "sha256": input_sha,
                    "rows_read": len(records),
                },
                "output": {"log": str(runs_dir / run.run_id / "layer1_log.json")},
            },
        )
        for asset, rec in zip(log["assets"], records, strict=True):  # a docket is not unique: the id is (F-15)
            asset["ruling_id"] = rec.ruling_id
            asset["decision_date"] = rec.decision_date
        manifest = _write(
            runs_dir / run.run_id,
            records,
            log,
            {
                "run_id": run.run_id,
                "step": STEP,
                "version": version,
                "profile": profile,
                "profile_version": profile_label,
                "population": population,
                "rulings": len(records),
                "kept": kept,
                "dropped": len(records) - kept,
                "ledger_rows": sum(outcomes.values()),
                "outcomes": {o: outcomes[o] for o in OUTCOMES},
                "parity_with_courts": dict(parity),
                "parity_reference": parity_reference,
                "log_checks_passed": log["quality"]["all_checks_passed"],
                "golden": golden_result,
            },
        )
        if not log["quality"]["all_checks_passed"]:
            raise RuntimeError("layer1 log closure checks failed")
        if golden_result["status"] == "mismatch":
            raise RuntimeError(
                f"golden check failed: {STEP} {version} no longer decides as {golden_result['expected']} certifies "
                f"({', '.join(golden_result['differs'])} differ); a changed decision needs a new version (D-064)"
            )
        with conn.transaction(), conn.cursor() as cur:
            _load(cur, run, records, rule_ids)
            values = {
                "rulings_in": len(records),
                "kept": kept,
                "dropped": len(records) - kept,
                "parity_same": parity["same"],
                "parity_different": parity["different"],
                "rubric_from_title": sum(1 for r in records if r.rubric_source == "gegenstand_head"),
                "ledger_rows": sum(outcomes.values()),
            }
            values |= {f"outcome_{o}": outcomes[o] for o in OUTCOMES}
            values |= {f"reason_{code.lower()}": n for code, n in by_reason.items()}
            metrics(cur, run, STEP, values)
            matched = golden_result["status"] == "matched"
            events(
                cur,
                run,
                STEP,
                [
                    (1, "info", "layer1.run.decided", f"{len(records)} rulings, {kept} kept", values, None, None),
                    (
                        2,
                        "info" if not mismatches else "warning",
                        "layer1.parity.checked",
                        f"decisions compared with the frozen reference {REFERENCE_SOURCE}",
                        {"different": parity["different"], "first": mismatches[:20], "reference": parity_reference},
                        None,
                        None,
                    ),
                    (
                        3,
                        "info",
                        "layer1.files.written",
                        "decisions.jsonl, layer1_log.json, manifest.json",
                        manifest["files"],
                        None,
                        None,
                    ),
                    (
                        4,
                        "info" if matched else "warning",
                        "layer1.golden.matched" if matched else "layer1.golden.not_comparable",
                        golden_result["reason"],
                        golden_result,
                        None,
                        None,
                    ),
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {
        "run_id": run.run_id,
        "version": version,
        "profile": f"{profile} {profile_label}",
        "rulings": len(records),
        "kept": kept,
        "dropped": len(records) - kept,
        "parity": dict(parity),
        "by_reason": dict(by_reason),
        "outcomes": {o: outcomes[o] for o in OUTCOMES},
        "golden": golden_result["status"],
        "files": str(runs_dir / run.run_id),
    }


# --- verify (F-16) ------------------------------------------------------------------------------------------------

_ASSESSMENTS_SQL = """
SELECT a.assessment_id::text, a.ruling_id::text, r.docket, r.decision_date::text, a.input_text_id::text,
       a.input_fingerprint, a.in_suva_scope::text, a.reason_code, a.score_0_100, a.explanation_de
FROM triage.assessment a JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
WHERE a.run_id = %s AND a.step = 'layer1_filter' AND a.repetition_idx = 0
"""
_LEDGER_SQL = """
SELECT ar.assessment_id::text, ar.ordinal, rl.rule_code, ar.effect::text, ar.outcome::text, ar.evidence_field,
       ar.examined_value, ar.char_start, ar.char_end, ar.matched_text, ar.detail
FROM triage.assessment_reason ar
JOIN triage.assessment a ON a.assessment_id = ar.assessment_id
JOIN ops.rule rl ON rl.rule_id = ar.rule_id
WHERE a.run_id = %s AND a.step = 'layer1_filter'
ORDER BY ar.assessment_id, ar.ordinal
"""
_LEDGER_KEYS = (
    "ordinal",
    "rule_code",
    "effect",
    "outcome",
    "evidence_field",
    "examined_value",
    "char_start",
    "char_end",
    "matched_text",
    "detail",
)


def verify_run(conn: psycopg.Connection, run_id: str, runs_dir: Path = RUNS_DIR) -> tuple[int, list[str]]:
    """Read-only proof that a run's files equal its database rows (F-16).

    The manifest's SHA-256 must match both files; every `decisions.jsonl` record must equal its assessment (scope,
    reason, explanation, fingerprint, text id, score) and its ledger, rule by rule; no assessment may lack a record.
    Returns (records read, differences); an empty list means the files and the database agree.
    """
    problems: list[str] = []
    run_dir = runs_dir / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return 0, [f"{manifest_path}: no manifest (wrong --runs-dir, or the run wrote no files)"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, sha in sorted(manifest.get("files", {}).items()):
        path = run_dir / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif sha256_file(path) != sha:
            problems.append(f"{name}: SHA-256 differs from manifest.json")
    records: dict[str, Layer1DecisionRecord] = {}
    decisions = run_dir / "decisions.jsonl"
    lines = decisions.read_text(encoding="utf-8").splitlines() if decisions.exists() else []
    for n, line in enumerate(lines, start=1):
        try:
            rec = Layer1DecisionRecord.model_validate_json(line)
        except ValidationError as exc:
            problems.append(f"decisions.jsonl line {n}: not a valid record ({exc.errors()[0]['msg']})")
            continue
        if rec.run_id != run_id:
            problems.append(f"decisions.jsonl line {n}: run_id {rec.run_id} is not {run_id}")
        if rec.ruling_id in records:
            problems.append(f"decisions.jsonl line {n}: ruling {rec.ruling_id} appears twice")
        records[rec.ruling_id] = rec
    for key, value in (
        ("rulings", len(records)),
        ("kept", sum(r.in_suva_scope == "potentially" for r in records.values())),
    ):
        if manifest.get(key) != value:
            problems.append(f"manifest.json: {key} {manifest.get(key)} but decisions.jsonl has {value}")

    with conn.cursor() as cur:
        cur.execute("SELECT status::text FROM ops.pipeline_run WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
        if row is None:
            return len(records), [*problems, f"run {run_id}: not in ops.pipeline_run"]
        if row[0] != "succeeded":
            problems.append(f"run {run_id}: status {row[0]}, not succeeded")
        cur.execute(_ASSESSMENTS_SQL, (run_id,))
        assessments = {r[1]: r for r in cur.fetchall()}
        cur.execute(_LEDGER_SQL, (run_id,))
        ledgers: dict[str, list[dict]] = {}
        for aid, *values in cur.fetchall():
            ledgers.setdefault(aid, []).append(dict(zip(_LEDGER_KEYS, values, strict=True)))
    conn.rollback()

    for ruling_id in sorted(set(assessments) - set(records)):
        problems.append(f"assessment of ruling {ruling_id} ({assessments[ruling_id][2]}): no record in decisions.jsonl")
    for ruling_id, rec in records.items():
        db = assessments.get(ruling_id)
        if db is None:
            problems.append(f"{rec.docket} ({ruling_id}): no assessment in the database")
            continue
        aid, _, docket, decided, text_id, fp, scope, reason, score, explanation = db
        file_values = (rec.docket, rec.decision_date, rec.text_id, rec.input_fingerprint, rec.in_suva_scope)
        db_values = (docket, decided, text_id, fp, scope)
        file_values += (rec.reason_code, rec.score_0_100, rec.explanation_de)
        db_values += (reason, float(score) if score is not None else None, explanation)
        names = ("docket", "decision_date", "text_id", "input_fingerprint", "in_suva_scope", "reason_code")
        names += ("score_0_100", "explanation_de")
        for name, f, d in zip(names, file_values, db_values, strict=True):
            if f != d:
                problems.append(f"{rec.docket}: {name} differs (file {f!r}, database {d!r})"[:400])
        file_ledger = [e.model_dump() for e in rec.evaluations]
        db_ledger = ledgers.get(aid, [])
        if len(file_ledger) != len(db_ledger):
            problems.append(f"{rec.docket}: {len(file_ledger)} evaluations in the file, {len(db_ledger)} ledger rows")
        for f, d in zip(file_ledger, db_ledger, strict=False):
            for key in _LEDGER_KEYS:
                if f[key] != d[key]:
                    problems.append(
                        f"{rec.docket}: rule {f['rule_code']} {key} differs (file {f[key]!r}, database {d[key]!r})"[
                            :400
                        ]
                    )
    return len(records), problems

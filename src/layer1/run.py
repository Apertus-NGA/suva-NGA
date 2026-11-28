"""Run layer 1 over the corpus: files first, then the database (D-061, D-073; docs/LAYER1.md §6).

1. The run reads the `layer1_filter` version its profile pins, with its configuration and rules (D-064).
2. It decides every ruling, and checks each decision against `src/courts.py` (the reference, parity count).
3. It writes `data/runs/<run_id>/`: `decisions.jsonl` (one Layer1DecisionRecord per ruling), `layer1_log.json`
   (the `layer1-log-1` contract of docs/layer1_log.schema.json, built by `src.courts.build_layer1_log`, with
   its closure checks) and `manifest.json` (counts and SHA-256 of both files).
4. It loads them into the database in one transaction: one span, one assessment and its rule hits (with
   evidence) per ruling, events and metrics. Nothing is written if any row fails (all or nothing).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import psycopg

from src import courts
from src.db.pg import ROOT, sha256_file, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import Run, begin_run, events, fail_run, finish_run, metrics
from src.layer1.engine import Decision, Layer1Engine, RuleSpec, fingerprint
from src.layer1.models import Layer1Config, Layer1DecisionRecord

STEP = "layer1_filter"
_SUBJECT_RULES = frozenset(
    {"L1_KEEP_RUBRIC", "L1_KEEP_RUBRIC_MISSING", "L1_DROP_WRONG_COURT", "L1_DROP_WRONG_LETTER", "L1_DROP_RUBRIC_OUT"}
)
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
        """SELECT r.rule_code, r.definition ->> 'check', r.kind::text, cvr.ordinal, r.rule_id::text
           FROM ops.component_version_rule cvr JOIN ops.rule r ON r.rule_id = cvr.rule_id
           WHERE cvr.component_version_id = %s AND cvr.enabled ORDER BY cvr.ordinal""",
        (component_version_id,),
    )
    found = cur.fetchall()
    rules = [RuleSpec(code, check, kind, ordinal) for code, check, kind, ordinal, _ in found]
    return config, rules, {code: rid for code, *_, rid in found}, row[1]


def explain(decision: Decision, labels: dict[str, str]) -> str:
    """The German reason a lawyer reads (G5), built from the reason-code labels."""
    if decision.kept:
        text = f"Vorauswahl bestanden: {labels[decision.reason_code]}."
        others = sorted(
            {h.rule_code for h in decision.hits if h.effect == "keep" and h.rule_code != decision.reason_code}
        )
        if others:
            text += " Ebenso: " + "; ".join(labels[c] for c in others) + "."
    else:
        text = f"Von der Vorauswahl ausgeschlossen: {labels[decision.reason_code]}."
        flags = sorted({h.rule_code for h in decision.hits if h.effect == "flag"})
        if flags:
            text += " Hinweis: " + "; ".join(labels[c] for c in flags) + "."
    if decision.rubric_source == "gegenstand_head" and decision.rubric:
        text += f" ({labels.get('L1_SIGNAL_RUBRIC_FROM_TITLE', 'Rechtsgebiet aus dem Gegenstand')}: {decision.rubric})"
    return text


def _courts_row(docket: str, rubric_fields: dict[str, str | None], gegenstand: str | None, text: str | None) -> dict:
    """The reference decision of src/courts.py on the same inputs (its `area` is the first filled rubric field)."""
    area = rubric_fields.get("neuheiten") or rubric_fields.get("hf_legal_area")
    return courts.gate_record(docket, area, gegenstand, text)


def _log_row(reference: dict, decision: Decision) -> dict:
    """A `layer1-log-1` row for a decision that differs from src/courts.py: reasons and criteria from the rule hits."""
    subject_hit = next(h for h in decision.hits if h.rule_code in _SUBJECT_RULES)
    text_hit = next((h for h in decision.hits if h.effect == "keep" and h.evidence.field == "full_text"), None)
    if text_hit is not None:
        text_criterion = text_hit.evidence.matched.casefold()
    else:
        text_criterion = "empty_text" if decision.text == "text_absent" else "no_keep_term"
    return reference | {
        "subject": decision.subject,
        "subject_pass": decision.subject in ("kept_subject", "subject_missing"),
        "subject_criterion": subject_hit.evidence.matched.casefold(),
        "text": decision.text,
        "text_pass": decision.text in ("kept_text", "kept_contract"),
        "text_criterion": text_criterion,
        "text_blocked_term": None,
        "path": courts._path(decision.subject, decision.text),
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


def _load(cur: psycopg.Cursor, run: Run, records: list[Layer1DecisionRecord], rule_ids: dict[str, str]) -> None:
    """Spans, assessments and rule hits of every ruling. Deterministic ids: reloading the same run is a no-op."""
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
                json.dumps({"subject": rec.subject, "text": rec.text}),
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
        for ordinal, hit in enumerate(rec.hits, start=1):
            ev = hit.evidence
            field = f"rubric:{ev.source}" if ev.field == "rubric" else ev.field
            reasons.append(
                (
                    assessment_id,
                    ordinal,
                    rule_ids[hit.rule_code],
                    hit.rule_code,
                    hit.effect,
                    field,
                    ev.start,
                    ev.end,
                    ev.matched,
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
           status,
                                 started_at, ended_at, attributes)
           VALUES (%s, %s, %s, 'layer1_filter', 'layer1.decide', %s, %s, 'ok', now(), now(), %s) ON CONFLICT DO
               NOTHING""",
        spans,
    )
    cur.executemany(
        """INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id,
           input_text_id,
                                          input_fingerprint, in_suva_scope, outcome, score_raw, score_0_100,
                                              score_source,
                                          reason_code, explanation_de, mode, started_at, finished_at)
           VALUES (%s, %s, %s, 'layer1_filter', %s, %s, %s, %s, %s, 'ok', %s, %s, %s, %s, %s, 'LIVE', now(), now())
           ON CONFLICT DO NOTHING""",
        assessments,
    )
    cur.executemany(
        """INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, evidence_field,
                                                 char_start, char_end, matched_text)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        reasons,
    )
    events(cur, run, STEP, evts)


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
        courts_rows: list[dict] = []
        parity = Counter()
        mismatches: list[str] = []
        with conn.cursor(name="layer1_rulings") as cur:
            cur.itersize = 500
            cur.execute(_RULINGS_SQL.format(where=where), args)
            for ruling_id, docket, decided, gegenstand, text_id, text, text_sha, neuheiten, legal_area in cur:
                rubric_fields = {"neuheiten": neuheiten, "hf_legal_area": legal_area}
                decision = engine.decide(docket, rubric_fields, gegenstand, text)
                reference = _courts_row(docket, rubric_fields, gegenstand, text)
                same = (reference["kept"], reference["subject"], reference["text"]) == (
                    decision.kept,
                    decision.subject,
                    decision.text,
                )
                parity["same" if same else "different"] += 1
                if not same and len(mismatches) < 50:
                    mismatches.append(docket)
                courts_rows.append(reference if same else _log_row(reference, decision))
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
                        hits=list(decision.hits),
                        explanation_de=explain(decision, labels),
                    )
                )
        conn.commit()  # close the named cursor's transaction
        if not records:
            raise RuntimeError("layer 1 read 0 rulings: load the base dataset first (G6: a step with 0 output fails)")
        kept = sum(1 for r in records if r.in_suva_scope == "potentially")
        by_reason = Counter(r.reason_code for r in records)
        log = courts.build_layer1_log(
            courts_rows,
            {
                "run_id": run.run_id,
                "phase": "layer1",
                "started_at": "",
                "finished_at": "",
                "selection": population or "all",
                "batch_size": 500,
                "code": f"src/layer1/engine.py ({STEP} {version})",
                "input": {
                    "path": "postgresql: corpus.ruling",
                    "format": "database",
                    "bytes": 0,
                    "sha256": "",
                    "rows_read": len(records),
                },
                "output": {"log": str(runs_dir / run.run_id / "layer1_log.json")},
            },
        )
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
                "parity_with_courts": dict(parity),
                "log_checks_passed": log["quality"]["all_checks_passed"],
            },
        )
        if not log["quality"]["all_checks_passed"]:
            raise RuntimeError("layer1 log closure checks failed")
        with conn.transaction(), conn.cursor() as cur:
            _load(cur, run, records, rule_ids)
            values = {
                "rulings_in": len(records),
                "kept": kept,
                "dropped": len(records) - kept,
                "parity_same": parity["same"],
                "parity_different": parity["different"],
                "rubric_from_title": sum(1 for r in records if r.rubric_source == "gegenstand_head"),
            }
            values |= {f"reason_{code.lower()}": n for code, n in by_reason.items()}
            metrics(cur, run, STEP, values)
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
                        "decisions compared with src/courts.py",
                        {"different": parity["different"], "first": mismatches[:20]},
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
        "files": str(runs_dir / run.run_id),
    }

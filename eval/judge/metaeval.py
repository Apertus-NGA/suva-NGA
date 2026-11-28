"""Does the judge deserve trust? Measures it on cases whose true label is known (docs/JUDGE.md §5).

    uv run python -m eval.judge.metaeval run --split dev            # tune prompts here
    uv run python -m eval.judge.metaeval run --split test --reps 2  # report this, once
    uv run python -m eval.judge.metaeval sheet --split test         # blind sheet for a human annotator
    uv run python -m eval.judge.metaeval kappa --sheet <file.csv>   # judge against the human labels

Positive cases: the summary Suva's experts wrote in the ruling's own language (expected PASS). Negative
cases: that summary after one controlled defect (`perturb.py`), expected FAIL on the criterion the defect
targets. Per criterion: sensitivity (defects caught), specificity (expert texts accepted), Cohen's kappa
against the known labels, and, with two repetitions, how often the judge agrees with itself.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

from eval.judge import data
from eval.judge.core import CRITERIA, VERSION, Item, Verdict, applicable, cohen_kappa, wilson
from eval.judge.perturb import EDITS, Context
from eval.judge.runner import DEFAULT_WORKERS, Cache, Task, live_transport, run_tasks, token_totals

ROOT = data.ROOT
# Written before the first measurement (docs/EVAL.md §1.1). A criterion below a bar is reported as not validated.
COURT_PROSE_POSITIVES = ("T1", "T3")  # known PASS = a passage of the ruling itself (data.court_passage)
THRESHOLDS = {
    "sensitivity": 0.80,
    "specificity": 0.80,
    "self_agreement": 0.90,
    "unusable_share": 0.05,
    "human_kappa": 0.60,
}


@dataclass(frozen=True)
class Case:
    case_id: str
    criterion: str
    expected: str  # PASS, FAIL, or BASELINE (Suva's text where it is not a clean positive: reported, not scored)
    kind: str  # "expert", "court_prose" or the name of the defect
    item: Item


def build_cases(split: str, criteria: list[str], limit: int | None = None) -> tuple[list[Case], dict[str, int]]:
    refs = [r for r in data.references().values() if r.split == split and r.ruling_language in ("de", "fr")]
    refs.sort(key=lambda r: r.docket)
    if limit:
        refs = refs[:limit]
    all_refs = data.references()
    texts = data.sources([r.docket for r in refs])
    skipped = {"no_source": 0, "source_too_long": 0}
    cases: list[Case] = []
    for ref in refs:
        src = texts.get(ref.docket)
        if not src:
            skipped["no_source"] += 1
            continue
        if len(src["text"]) > data.MAX_SOURCE_CHARS:
            skipped["source_too_long"] += 1
            continue
        own = ref.ruling_language
        other = "fr" if own == "de" else "de"
        good = ref.text(own)
        base = dict(docket=ref.docket, source=src["text"], source_language=src["language"])
        examples = data.style_examples(all_refs, own, ref.docket)
        ctx = Context(language=own, parallel=ref.text(other), outcome=src["outcome"])
        court = data.court_passage(src["text"]) if src["language"] == own else None
        for cid in criteria:
            base_text = good
            if cid == "R1":
                # Expected PASS: the expert's own text in the other language conveys the same legal points.
                if (ref.docket, other) not in data.MISTRANSLATED:
                    item = Item(language=other, summary=ref.text(other), reference=good, reference_language=own, **base)
                    cases.append(Case(f"{ref.docket}|R1|expert", "R1", "PASS", "expert", item))
            elif cid in COURT_PROSE_POSITIVES:
                # Suva's texts carry language slips of their own, so they are a baseline here, not a known PASS.
                item = Item(language=own, summary=good, examples=examples, **base)
                cases.append(Case(f"{ref.docket}|{cid}|expert", cid, "BASELINE", "expert", item))
                if not court:
                    continue
                base_text = court
                item = Item(language=own, summary=court, examples=examples, **base)
                cases.append(Case(f"{ref.docket}|{cid}|court_prose", cid, "PASS", "court_prose", item))
            else:
                item = Item(language=own, summary=good, examples=examples, **base)
                cases.append(Case(f"{ref.docket}|{cid}|expert", cid, "PASS", "expert", item))
            for edit in EDITS[cid]:
                damaged = edit(base_text, ctx)
                if not damaged or damaged == base_text:
                    continue
                item = Item(
                    language=own,
                    summary=damaged,
                    examples=examples,
                    reference=good if cid == "R1" else "",
                    reference_language=own if cid == "R1" else "",
                    **base,
                )
                cases.append(Case(f"{ref.docket}|{cid}|{edit.__name__}", cid, "FAIL", edit.__name__, item))
    return [c for c in cases if applicable(c.criterion, c.item)], skipped


def rate(hit: int, total: int) -> dict[str, object]:
    low, high = wilson(hit, total)
    return {"n": total, "rate": round(hit / total, 4) if total else None, "ci95": [low, high]}


def measure(cases: list[Case], verdicts: dict[str, Verdict], second: dict[str, Verdict] | None = None) -> dict:
    report = {}
    for cid in sorted({c.criterion for c in cases}, key=list(CRITERIA).index):
        mine = [c for c in cases if c.criterion == cid]
        expert = [c for c in mine if c.kind == "expert" and verdicts[c.case_id].status in ("PASS", "FAIL")]
        mine = [c for c in mine if c.expected != "BASELINE"]
        valid = [c for c in mine if verdicts[c.case_id].status in ("PASS", "FAIL")]
        negatives = [c for c in valid if c.expected == "FAIL"]
        positives = [c for c in valid if c.expected == "PASS"]
        caught = sum(verdicts[c.case_id].status == "FAIL" for c in negatives)
        accepted = sum(verdicts[c.case_id].status == "PASS" for c in positives)
        entry = {
            "name": CRITERIA[cid]["name"],
            "sensitivity": rate(caught, len(negatives)),
            "specificity": rate(accepted, len(positives)),
            "kappa_vs_known_label": cohen_kappa(
                [c.expected for c in valid], [verdicts[c.case_id].status for c in valid]
            ),
            "unusable": rate(len(mine) - len(valid), len(mine)),
            "suva_texts_passing": rate(sum(verdicts[c.case_id].status == "PASS" for c in expert), len(expert)),
            "by_defect": {
                kind: rate(sum(verdicts[c.case_id].status == "FAIL" for c in negatives if c.kind == kind), n)
                for kind in sorted({c.kind for c in negatives})
                if (n := sum(c.kind == kind for c in negatives))
            },
        }
        if second is not None:
            both = [c for c in mine if {verdicts[c.case_id].status, second[c.case_id].status} <= {"PASS", "FAIL"}]
            entry["self_agreement"] = rate(
                sum(verdicts[c.case_id].status == second[c.case_id].status for c in both), len(both)
            )
        sens, spec = entry["sensitivity"]["rate"], entry["specificity"]["rate"]
        entry["validated"] = bool(
            sens is not None
            and spec is not None
            and sens >= THRESHOLDS["sensitivity"]
            and spec >= THRESHOLDS["specificity"]
            and (entry["unusable"]["rate"] or 0) <= THRESHOLDS["unusable_share"]
            and (second is None or (entry["self_agreement"]["rate"] or 0) >= THRESHOLDS["self_agreement"])
        )
        report[cid] = entry
    return report


def command_run(args: argparse.Namespace) -> None:
    criteria = args.criteria or list(CRITERIA)
    cases, skipped = build_cases(args.split, criteria, args.limit)
    print(f"{len(cases)} cases on the {args.split} split, {skipped}")
    if args.dry_run:
        for cid in criteria:
            mine = [c for c in cases if c.criterion == cid]
            print(
                f"  {cid}: {sum(c.expected == 'PASS' for c in mine)} expert,"
                f" {sum(c.expected == 'FAIL' for c in mine)} damaged"
            )
        return
    transport, model, effort = live_transport()
    cache = Cache(data.DERIVED / "cache.jsonl")
    runs = []
    for repetition in range(args.reps):
        tasks = [Task(c.case_id, c.criterion, c.item, repetition) for c in cases]
        runs.append(run_tasks(tasks, transport, model=model, effort=effort, cache=cache, workers=args.workers))
    first = runs[0]
    name = args.split + (f"_{args.tag}" if args.tag else "")
    detail = data.DERIVED / f"metaeval_{name}.jsonl"  # holds quotes of Suva's texts: git-ignored
    detail.parent.mkdir(parents=True, exist_ok=True)
    with detail.open("w", encoding="utf-8") as handle:
        for case in cases:
            row = {
                "case_id": case.case_id,
                "expected": case.expected,
                "kind": case.kind,
                **first[case.case_id].as_dict(),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "rubric": VERSION,
        "judge_model": model,
        "served_models": sorted({v.served_model for v in first.values() if v.served_model}),
        "reasoning_effort": effort,
        "split": args.split,
        "cases": len(cases),
        "skipped": skipped,
        "repetitions": args.reps,
        "thresholds": THRESHOLDS,
        "tokens": token_totals(v for run in runs for v in run.values()),
        "criteria": measure(cases, first, runs[1] if args.reps > 1 else None),
    }
    out = ROOT / "results" / f"judge_metaeval_{name}.json"  # numbers only (D-031)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for cid, entry in report["criteria"].items():
        print(
            f"  {cid} sensitivity {entry['sensitivity']['rate']} (n={entry['sensitivity']['n']})"
            f" specificity {entry['specificity']['rate']} (n={entry['specificity']['n']})"
            f" unusable {entry['unusable']['rate']} suva_texts_passing {entry['suva_texts_passing']['rate']}"
            f" validated {entry['validated']}"
        )
    print(f"wrote {out.relative_to(ROOT)} and {detail.relative_to(ROOT)}; tokens {report['tokens']}")


def command_sheet(args: argparse.Namespace) -> None:
    """A blind sheet: the annotator sees the texts and the question, not the expected label or the judge's."""
    cases, _ = build_cases(args.split, args.criteria or list(CRITERIA), args.limit)
    random.Random(args.seed).shuffle(cases)
    cases = cases[: args.count]
    path = data.DERIVED / f"human_sheet_{args.split}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "criterion", "question", "language", "summary", "reference", "docket", "human"])
        for n, case in enumerate(cases):
            c = CRITERIA[case.criterion]
            blind_id = f"{n:03d}|{case.case_id}" if args.show_ids else f"{n:03d}"
            writer.writerow(
                [
                    blind_id,
                    case.criterion,
                    c["question"],
                    case.item.language,
                    case.item.summary,
                    case.item.reference,
                    case.item.docket,
                    "",
                ]
            )
    key = path.with_suffix(".key.json")
    key.write_text(json.dumps({f"{n:03d}": c.case_id for n, c in enumerate(cases)}, indent=1), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(cases)} rows) and its key; fill the `human` column with PASS or FAIL")


def command_kappa(args: argparse.Namespace) -> None:
    sheet = Path(args.sheet)
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))
    split = sheet.stem.rsplit("_", 1)[-1]
    judged = {}
    for line in (data.DERIVED / f"metaeval_{split}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        judged[row["case_id"]] = row["status"]
    pairs: dict[str, list[tuple[str, str]]] = {}
    with sheet.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            human = row["human"].strip().upper()
            case_id = key[row["case_id"][:3]]
            if human in ("PASS", "FAIL") and judged.get(case_id) in ("PASS", "FAIL"):
                pairs.setdefault(row["criterion"], []).append((human, judged[case_id]))
    everything = [p for group in pairs.values() for p in group]
    report = {
        "all": {"n": len(everything), "kappa": cohen_kappa([h for h, _ in everything], [j for _, j in everything])}
    }
    for cid, group in sorted(pairs.items()):
        report[cid] = {"n": len(group), "kappa": cohen_kappa([h for h, _ in group], [j for _, j in group])}
    out = ROOT / "results" / f"judge_human_agreement_{split}.json"
    out.write_text(
        json.dumps({"threshold": THRESHOLDS["human_kappa"], "agreement": report}, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "sheet"):
        p = sub.add_parser(name)
        p.add_argument("--split", choices=("dev", "test"), required=True)
        p.add_argument("--criteria", nargs="*")
        p.add_argument("--limit", type=int, help="first N rulings of the split")
    run, sheet = sub.choices["run"], sub.choices["sheet"]
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    run.add_argument("--dry-run", action="store_true", help="count the cases, call nothing")
    run.add_argument("--tag", default="", help="suffix of the output files, to compare models side by side")
    sheet.add_argument("--count", type=int, default=60)
    sheet.add_argument("--seed", type=int, default=20261127)
    sheet.add_argument("--show-ids", action="store_true")
    sub.add_parser("kappa").add_argument("--sheet", required=True)
    args = parser.parse_args()
    {"run": command_run, "sheet": command_sheet, "kappa": command_kappa}[args.command](args)


if __name__ == "__main__":
    main()

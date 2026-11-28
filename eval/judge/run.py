"""Judge a set of generated summaries (docs/JUDGE.md §6).

    uv run python -m eval.judge.run --candidates data/trial --name v2

`--candidates` is a directory of `<docket>.json` files as `src/summarize/summarize.py` writes them, or a
JSON-lines file of {"docket", "language", "summary"}. For each summary: the deterministic checks, then one
judge call per criterion. R1 runs only for rulings that have a Suva reference summary. The per-summary
detail (quotes included) goes to `data/derived/judge/` (git-ignored); the numbers go to `results/`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.judge import data
from eval.judge.checks import run_checks
from eval.judge.core import CRITERIA, VERSION, Item, applicable, score, wilson
from eval.judge.runner import DEFAULT_WORKERS, Cache, Task, live_transport, run_tasks, token_totals

ROOT = data.ROOT


def length_bands(refs: dict[str, data.Reference]) -> dict[str, tuple[int, int]]:
    """Words, 10th to 90th percentile of Suva's 55 summaries, per language (D-053: the exports set the length)."""
    bands = {}
    for language in ("de", "fr"):
        counts = sorted(len(r.text(language).split()) for r in refs.values())
        bands[language] = (counts[len(counts) // 10], counts[(len(counts) * 9) // 10])
    return bands


def build_items(rows: list[dict[str, str]], refs: dict[str, data.Reference]) -> tuple[list[Item], dict[str, int]]:
    texts = data.sources(sorted({r["docket"] for r in rows}))
    skipped = {"no_source": 0, "source_too_long": 0, "empty_summary": 0}
    items = []
    for row in rows:
        src = texts.get(row["docket"])
        if not row["summary"].strip():
            skipped["empty_summary"] += 1
        elif not src:
            skipped["no_source"] += 1
        elif len(src["text"]) > data.MAX_SOURCE_CHARS:
            skipped["source_too_long"] += 1
        else:
            ref = refs.get(row["docket"])
            # The reference is read in the ruling's own language (the expert's original), German for an Italian ruling.
            ref_language = (ref.ruling_language if ref.ruling_language in ("de", "fr") else "de") if ref else ""
            items.append(
                Item(
                    docket=row["docket"],
                    language=row["language"],
                    summary=row["summary"].strip(),
                    source=src["text"],
                    source_language=src["language"],
                    reference=ref.text(ref_language) if ref else "",
                    reference_language=ref_language,
                    examples=data.style_examples(refs, row["language"], row["docket"]),
                )
            )
    return items, skipped


def aggregate(results: list[dict]) -> dict:
    out: dict = {"summaries": len(results), "by_language": {}}
    for scope, rows in [("all", results)] + [
        (lang, [r for r in results if r["language"] == lang]) for lang in ("de", "fr")
    ]:
        if not rows:
            continue
        criteria = {}
        for cid, c in CRITERIA.items():
            judged = [r["verdicts"][cid] for r in rows if r["verdicts"].get(cid) in ("PASS", "FAIL")]
            unusable = sum(1 for r in rows if cid in r["verdicts"] and r["verdicts"][cid] not in ("PASS", "FAIL"))
            passed = sum(v == "PASS" for v in judged)
            criteria[cid] = {
                "name": c["name"],
                "judged": len(judged),
                "pass_rate": round(passed / len(judged), 4) if judged else None,
                "ci95": list(wilson(passed, len(judged))),
                "no_verdict": unusable,
            }
        scores = [r["score"]["score"] for r in rows if r["score"]["score"] is not None]
        block = {
            "summaries": len(rows),
            "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
            "usable_share": round(sum(r["score"]["usable"] for r in rows) / len(rows), 4),
            "criteria": criteria,
            "checks_flagged": {name: sum(bool(r["checks"][name]) for r in rows) for name in rows[0]["checks"]},
        }
        if scope == "all":
            out.update(block)
        else:
            out["by_language"][scope] = block
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--name", required=True, help="label of this run, used in the output file names")
    parser.add_argument("--criteria", nargs="*")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dry-run", action="store_true", help="run the deterministic checks only, call nothing")
    args = parser.parse_args()

    refs = data.references()
    bands = length_bands(refs)
    items, skipped = build_items(data.candidates(args.candidates), refs)
    criteria = args.criteria or list(CRITERIA)
    tasks = [Task(f"{n}|{cid}", cid, item) for n, item in enumerate(items) for cid in criteria if applicable(cid, item)]
    print(f"{len(items)} summaries, {len(tasks)} judge calls, skipped {skipped}")
    verdicts = {}
    model = effort = "none (dry run)"
    if not args.dry_run:
        transport, model, effort = live_transport()
        cache = Cache(data.DERIVED / "cache.jsonl")
        verdicts = run_tasks(tasks, transport, model=model, effort=effort, cache=cache, workers=args.workers)
    results = []
    for n, item in enumerate(items):
        mine = {cid: verdicts[f"{n}|{cid}"] for cid in criteria if f"{n}|{cid}" in verdicts}
        results.append(
            {
                "docket": item.docket,
                "language": item.language,
                "checks": run_checks(item.summary, item.language, bands[item.language]),
                "verdicts": {cid: v.status for cid, v in mine.items()},
                "score": score({cid: v.status for cid, v in mine.items()}),
                "detail": {cid: v.as_dict() for cid, v in mine.items()},
            }
        )
    detail = data.DERIVED / f"run_{args.name}.jsonl"
    detail.parent.mkdir(parents=True, exist_ok=True)
    detail.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    report = {
        "rubric": VERSION,
        "judge_model": model,
        "reasoning_effort": effort,
        "run": args.name,
        "skipped": skipped,
        "length_band_words": bands,
        "tokens": token_totals(verdicts.values()),
        **aggregate(results),
    }
    out = ROOT / "results" / f"judge_run_{args.name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"mean score {report.get('mean_score')}, usable {report.get('usable_share')}")
    for cid, entry in report.get("criteria", {}).items():
        print(f"  {cid} {entry['name']}: {entry['pass_rate']} of {entry['judged']} (no verdict: {entry['no_verdict']})")
    print(f"wrote {out.relative_to(ROOT)} and {detail.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

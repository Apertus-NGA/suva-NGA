"""Before/after measurement of the refine loop on the judge's development pool (docs/JUDGE.md; AGENTS.md G10).

    uv run python -m eval.refine_eval sample
    uv run python -m eval.refine_eval drafts  --set iterate          # the current pipeline's fiches (live, cached)
    uv run python -m eval.refine_eval refine  --set iterate --name r1  # refine them (live, cached)
    uv run python -m eval.refine_eval judge   --set iterate --name r1  # judge before and after (cached per text)
    uv run python -m eval.refine_eval report  --set iterate --name r1

Two disjoint sets of development rulings: `iterate` (used while tuning the steps) and `holdout` (run once at the
end, never looked at while tuning). The test split of the judge is never used. Per-summary files hold Suva-derived
text and stay in data/derived/refine/ (git-ignored, D-031); the aggregate goes to results/refine_eval_<name>.json.
The judge is not validated with its current rubric (docs/JUDGE.md §5): every judge number is provisional.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "derived" / "refine"
EXCLUDED = ("8C_177/2025", "8C_224/2025", "8C_21/2025", "8C_44/2025", "8C_455/2025")  # few-shot, one-line fiches
ITERATE_SIZE, SEED = 12, 7
WORKERS = 4  # rulings in parallel; the client caps concurrent calls at LLM_CONCURRENCY (team total <= 16, G2)

# Pass bars, written before the first measurement (G10). "after" is refine, "before" the current pipeline.
BARS = [
    {"id": "R-B1", "metric": "code checks failing (sum over summaries)", "rule": "after < before"},
    {"id": "R-B2", "metric": "usable share (all critical criteria pass)", "rule": "after >= before + 0.10"},
    {"id": "R-B3", "metric": "mean judge score", "rule": "after > before"},
    {"id": "R-B4", "metric": "F1, F2, F3 pass rates", "rule": "no drop of more than 0.05"},
    {"id": "R-B5", "metric": "Apertus calls per summary, median", "rule": "<= 20"},
]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def sets() -> dict[str, list[str]]:
    """The two disjoint sets of development rulings, stratified by the ruling's language."""
    from eval.judge import data
    from suva_data import db

    dev = sorted(d for d, ref in data.references().items() if ref.split == "dev" and d not in EXCLUDED)
    with db.connect() as conn:
        language = dict(conn.execute("SELECT docket, language FROM rulings WHERE docket = ANY(%s)", (dev,)).fetchall())
    rng = random.Random(SEED)
    iterate: list[str] = []
    for lang in ("de", "it", "fr"):
        pool = sorted(d for d in dev if language.get(d) == lang)
        rng.shuffle(pool)
        share = {"de": 3, "it": 1, "fr": ITERATE_SIZE - 4}[lang]
        iterate += pool[:share]
    holdout = [d for d in dev if d not in iterate and d in language]
    return {"iterate": sorted(iterate), "holdout": sorted(holdout)}


def _rulings(dockets: list[str]) -> list[dict]:
    from src.summarize import pipeline
    from suva_data import db

    with db.connect() as conn:
        rows = conn.execute("SELECT id, docket, language FROM rulings WHERE docket = ANY(%s)", (dockets,)).fetchall()
        out = []
        for rid, docket, language in rows:
            ruling = pipeline.load_ruling(conn, rid)
            ruling["language"] = language
            ruling["shots"] = {lang: pipeline.examples(conn, lang, docket) for lang in pipeline.LANGUAGES}
            ruling["lexicon"] = {
                lang: "\n".join(b for (b,) in conn.execute(
                    "SELECT g.body FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id "
                    "WHERE g.is_current AND g.language = %s AND r.docket <> %s", (lang, docket)).fetchall())
                for lang in pipeline.LANGUAGES
            }  # fmt: skip
            out.append(ruling)
    return sorted(out, key=lambda r: r["docket"])


def drafts(name_set: str) -> None:
    """The current pipeline's finished fiches, unchanged (pipeline.write: generate, repair, finish)."""
    from src.summarize import pipeline, summarize

    rulings = _rulings(sets()[name_set])

    def one(ruling: dict) -> list[dict]:
        result = pipeline.write(ruling, ruling["shots"], lambda m: summarize.chat(m, mode="live"))
        return [{"docket": ruling["docket"], "language": lang, "category": result["category"], "text": f["text"],
                 "problems": f["problems"]} for lang, f in result["languages"].items()]  # fmt: skip

    with ThreadPoolExecutor(WORKERS) as pool:
        rows = [row for batch in pool.map(one, rulings) for row in batch]
    _write(OUT / f"drafts_{name_set}.jsonl", rows)
    print(f"{len(rows)} drafts -> {OUT / f'drafts_{name_set}.jsonl'}")


def refine_all(name_set: str, name: str, steps: list[str] | None = None) -> None:
    from src.llm.client import client_from_env
    from src.summarize.refine import Model, evidence, gateway, read_record, refine_fiche
    from src.summarize.refine.steps import default_steps

    draft_rows = {(r["docket"], r["language"]): r for r in _jsonl(OUT / f"drafts_{name_set}.jsonl")}
    rulings = _rulings(sets()[name_set])
    client = client_from_env("live")
    transport = gateway(client=client)

    def one(ruling: dict) -> list[dict]:
        try:
            return _one(ruling)
        except Exception as exc:  # noqa: BLE001  one ruling's failure is reported, the others go on
            print(f"{ruling['docket']}: FAILED {type(exc).__name__}: {exc}", flush=True)
            return []

    def _one(ruling: dict) -> list[dict]:
        model = Model(transport, budget=40)
        record = read_record(ruling["text"], evidence.passages(ruling["text"]), model)
        rows = []
        for lang in ("de", "fr"):
            draft = draft_rows[(ruling["docket"], lang)]
            chosen = [s for s in default_steps() if steps is None or s.id in steps]
            per = Model(transport, budget=24)
            result = refine_fiche(draft["text"], lang, ruling["text"], draft["category"], per, record,
                                  ruling["lexicon"][lang], ruling["language"], chosen)  # fmt: skip
            rows.append({"docket": ruling["docket"], "language": lang, "record": record, **result.as_dict(),
                         "model_log": per.log})  # fmt: skip
            statuses = " ".join(f"{o.step}:{o.status}" for o in result.trace)
            print(f"{ruling['docket']} {lang}: {result.calls} calls, {statuses}", flush=True)
        return rows

    with ThreadPoolExecutor(WORKERS) as pool:
        rows = [row for batch in pool.map(one, rulings) for row in batch]
    client.close()
    _write(OUT / f"refined_{name_set}_{name}.jsonl", rows)
    print(f"{len(rows)} refined -> {OUT / f'refined_{name_set}_{name}.jsonl'}")


def judge(name_set: str, name: str) -> None:
    before = [{"docket": r["docket"], "language": r["language"], "summary": r["text"]}
              for r in _jsonl(OUT / f"drafts_{name_set}.jsonl")]  # fmt: skip
    after = [{"docket": r["docket"], "language": r["language"], "summary": r["text"]}
             for r in _jsonl(OUT / f"refined_{name_set}_{name}.jsonl")]  # fmt: skip
    for label, rows in ((f"refine_{name_set}_before", before), (f"refine_{name_set}_{name}", after)):
        path = OUT / f"{label}.judge.jsonl"
        _write(path, rows)
        subprocess.run([sys.executable, "-m", "eval.judge.run", "--candidates", str(path), "--name", label],
                       check=True, cwd=ROOT)  # fmt: skip


def _detail(label: str) -> dict[tuple[str, str], dict]:
    rows = _jsonl(ROOT / "data" / "derived" / "judge" / f"run_{label}.jsonl")
    return {(r["docket"], r["language"]): r for r in rows}


def report(name_set: str, name: str) -> dict:
    from statistics import median

    before, after = _detail(f"refine_{name_set}_before"), _detail(f"refine_{name_set}_{name}")
    refined = {(r["docket"], r["language"]): r for r in _jsonl(OUT / f"refined_{name_set}_{name}.jsonl")}
    keys = sorted(set(before) & set(after))
    criteria = sorted({c for r in before.values() for c in r["verdicts"]})

    def rate(side: dict, cid: str, lang: str | None) -> float | None:
        vals = [side[k]["verdicts"].get(cid) for k in keys if lang in (None, k[1])]
        judged = [v for v in vals if v in ("PASS", "FAIL")]
        return round(sum(v == "PASS" for v in judged) / len(judged), 3) if judged else None

    def block(lang: str | None) -> dict:
        ks = [k for k in keys if lang in (None, k[1])]
        out = {"summaries": len(ks)}
        for label, side in (("before", before), ("after", after)):
            scores = [side[k]["score"]["score"] for k in ks if side[k]["score"]["score"] is not None]
            out[label] = {
                "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
                "usable_share": round(sum(side[k]["score"]["usable"] for k in ks) / len(ks), 3) if ks else None,
                "criteria": {c: rate(side, c, lang) for c in criteria},
            }
        out["code_checks_failing"] = {
            "before": sum(len(refined[k]["checks_before"]) for k in ks if k in refined),
            "after": sum(len(refined[k]["checks_after"]) for k in ks if k in refined),
        }
        return out

    steps: dict[str, dict] = {}
    for row in refined.values():
        for outcome in row["trace"]:
            s = steps.setdefault(outcome["step"], {"passed": 0, "corrected": 0, "needs_review": 0, "skipped": 0,
                                                   "patches_kept": 0, "patches_refused": 0, "calls": 0})  # fmt: skip
            s[outcome["status"]] += 1
            s["calls"] += outcome["calls"]
            for f in outcome["findings"]:
                s["patches_kept" if f.get("accepted") else "patches_refused"] += 1
    result = {
        "run": name,
        "set": name_set,
        "judge": "provisional (rubric not validated, docs/JUDGE.md §5)",
        "bars": BARS,
        "all": block(None),
        "by_language": {lang: block(lang) for lang in ("de", "fr")},
        "steps": steps,
        "calls_per_summary_median": median([r["calls"] for r in refined.values()]) if refined else None,
        "changed_summaries": sum(r["text"] != r["draft"] for r in refined.values()),
    }
    path = ROOT / "results" / f"refine_eval_{name_set}_{name}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    a = result["all"]
    print(f"{name_set}/{name}: {a['summaries']} summaries, changed {result['changed_summaries']}, "
          f"calls median {result['calls_per_summary_median']}")  # fmt: skip
    for label in ("before", "after"):
        crit = " ".join(f"{c}={v}" for c, v in a[label]["criteria"].items())
        print(f"  {label:6} mean {a[label]['mean_score']} usable {a[label]['usable_share']}  {crit}")
    print(f"  code checks failing {a['code_checks_failing']}")
    for sid, s in steps.items():
        print(f"  step {sid}: {s}")
    return result


def show(name_set: str, name: str, docket: str | None = None) -> None:
    """Per summary: the draft, the refined text, each step's findings, and the judge's verdicts before and after."""
    refined = _jsonl(OUT / f"refined_{name_set}_{name}.jsonl")
    try:
        before, after = _detail(f"refine_{name_set}_before"), _detail(f"refine_{name_set}_{name}")
    except FileNotFoundError:
        before = after = {}
    for row in refined:
        if docket and row["docket"] != docket:
            continue
        key = (row["docket"], row["language"])
        print(f"\n===== {row['docket']} {row['language']}  calls {row['calls']}")
        if key in before and key in after:
            was, now = before[key]["verdicts"], after[key]["verdicts"]
            changed = {c: f"{was.get(c)}->{now.get(c)}" for c in was if was.get(c) != now.get(c)}
            print(f"judge {before[key]['score']['score']} -> {after[key]['score']['score']}  {changed}")
        print("--- draft:\n" + row["draft"] + "\n--- refined:\n" + row["text"])
        for outcome in row["trace"]:
            for f in outcome.get("findings", []):
                mark = "KEPT" if f.get("accepted") else "REFUSED"
                patch = (f.get("patch") or {}).get("text", "")
                print(f"  [{outcome['step']}] {mark} {f['reason'][:90]} {('-> ' + patch[:160]) if patch else ''}"
                      f"{('  WHY: ' + f['why_not'][:160]) if f.get('why_not') else ''}")  # fmt: skip
            if outcome.get("note"):
                print(f"  [{outcome['step']}] {outcome['status']}: {outcome['note'][:160]}")


def main() -> None:
    from src.summarize import summarize

    summarize.load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["sample", "drafts", "refine", "judge", "report", "show"])
    parser.add_argument("--set", default="iterate", choices=["iterate", "holdout"])
    parser.add_argument("--name", default="r1")
    parser.add_argument("--steps", nargs="*")
    parser.add_argument("--docket")
    args = parser.parse_args()
    if args.command == "sample":
        print(json.dumps(sets(), indent=1))
    elif args.command == "drafts":
        drafts(args.set)
    elif args.command == "refine":
        refine_all(args.set, args.name, args.steps)
    elif args.command == "judge":
        judge(args.set, args.name)
    elif args.command == "show":
        show(args.set, args.name, args.docket)
    else:
        report(args.set, args.name)


if __name__ == "__main__":
    main()

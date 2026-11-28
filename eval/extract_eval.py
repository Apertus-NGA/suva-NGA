"""Measure the extractive writer's choice of sentences against the sentences Suva's own fiche restates.

    uv run python -m eval.extract_eval filter --set iterate          # what the code filter keeps of Suva's choice
    uv run python -m eval.extract_eval choose --set iterate --name c1  # Apertus chooses (live, cached)
    uv run python -m eval.extract_eval report --set iterate --name c1  # results/extract_eval_<set>_<name>.json

Suva's choice is read by code: a sentence of Suva's fiche in the ruling's language is matched to the ruling
sentence it shares the largest share of its words with, when that share is at least MATCH (docs/EXTRACT.md §5).
Italian rulings have no fiche in their language and are left out of this measure. The sets are refine_eval's
(the judge's development rulings; the test split is never used). Per-ruling files hold Suva-derived text and stay
in data/derived/extract/ (git-ignored, D-031); only aggregates go to results/.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from pathlib import Path

from eval.refine_eval import ROOT, sets

OUT = ROOT / "data" / "derived" / "extract"
MATCH = 0.5
SOFT = 0.35  # a chosen sentence that shares a third of a Suva sentence's words says nearly the same thing
MIN_MATCH_WORDS = 4

# Pass bars, written before the first choice was measured (G10). "today" is the current pipeline's draft, read
# by the same matching: 3 % of Suva's sentences and 12 % of Suva's considerations on 27 drafts (28 Nov).
BARS = [
    {"id": "X-F1", "metric": "share of Suva's matched sentences the code filter keeps", "rule": ">= 0.90"},
    {"id": "X-C1", "metric": "sentence recall of the choice (mean per ruling)", "rule": ">= 0.40"},
    {"id": "X-C2", "metric": "consideration recall of the choice (mean per ruling)", "rule": ">= 0.60"},
    {"id": "X-C3", "metric": "sentence recall, choice minus a random choice of the same size", "rule": ">= 0.20"},
]


def words(text: str) -> set[str]:
    return set(re.findall(r"\w{4,}", text.lower()))


def match(fiche: str, ruling_sentences: list[str]) -> list[int | None]:
    """For each sentence of the fiche, the index of the ruling sentence it restates, or None."""
    from src.summarize.refine.draft import split_sentences

    out: list[int | None] = []
    targets = [words(s) for s in ruling_sentences]
    for sentence in split_sentences(" ".join(fiche.split())):
        mine = words(sentence)
        if len(mine) < MIN_MATCH_WORDS or not targets:
            continue
        share, index = max((len(mine & t) / len(mine), i) for i, t in enumerate(targets))
        out.append(index if share >= MATCH else None)
    return out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def gold(name_set: str) -> list[dict]:
    """Per ruling: the candidates, Suva's matched sentences among all sentences and among the candidates."""
    from src.summarize import pipeline
    from src.summarize.extract import candidates as cand
    from src.summarize.refine import evidence
    from suva_data import db

    rows = []
    with db.connect() as conn:
        for docket in sets()[name_set]:
            rid, language = conn.execute("SELECT id, language FROM rulings WHERE docket = %s", (docket,)).fetchone()
            body = conn.execute(
                "SELECT g.body FROM gold_summaries g WHERE g.ruling_id = %s AND g.is_current AND g.language = %s",
                (rid, language),
            ).fetchone()
            text = pipeline.load_ruling(conn, rid)["text"]
            found = cand.candidates(text)
            every = cand.sentences(evidence.passages(text))
            row = {"docket": docket, "language": language, "candidates": len(found.kept), "sentences": len(every),
                   "dropped": found.reasons()}  # fmt: skip
            if body is None:
                rows.append({**row, "gold": None})
                continue
            matched = [i for i in match(body[0], [s for _, s in every]) if i is not None]
            index = {(c.label, c.text): c.id for c in found.kept}
            reasons = {(label, s): why for label, why, s in found.dropped}
            chosen = [every[i] for i in dict.fromkeys(matched)]
            row["gold"] = {
                "fiche_sentences": len(match(body[0], [s for _, s in every])),
                "matched": len(chosen),
                "kept": [index[c] for c in chosen if c in index],
                "lost": [
                    {"label": c[0], "reason": reasons.get(c, "?"), "sentence": c[1][:160]}
                    for c in chosen
                    if c not in index
                ],  # fmt: skip
                "labels": sorted({c[0] for c in chosen}),
                "texts": [c[1] for c in chosen],
            }
            rows.append(row)
    return rows


def filter_report(name_set: str) -> dict:
    rows = gold(name_set)
    _write(OUT / f"gold_{name_set}.jsonl", rows)
    scored = [r for r in rows if r["gold"] and r["gold"]["matched"]]
    matched = sum(r["gold"]["matched"] for r in scored)
    kept = sum(len(r["gold"]["kept"]) for r in scored)
    lost: dict[str, int] = {}
    for r in scored:
        for item in r["gold"]["lost"]:
            lost[item["reason"]] = lost.get(item["reason"], 0) + 1
    summary = {
        "set": name_set,
        "rulings": len(rows),
        "rulings_with_matched_fiche": len(scored),
        "sentences_median": statistics.median(r["sentences"] for r in rows),
        "candidates_median": statistics.median(r["candidates"] for r in rows),
        "suva_sentences_matched": matched,
        "suva_sentences_kept_by_filter": kept,
        "filter_keeps": round(kept / matched, 3) if matched else None,
        "lost_by_reason": lost,
        "match_rate": round(matched / max(1, sum(r["gold"]["fiche_sentences"] for r in scored)), 3),
    }
    return summary


def top_labels(scores: dict[str, float]) -> list[str]:
    from src.summarize.extract.choose import top

    return top(scores)


def recall(chosen: list[str], wanted: list[str]) -> float:
    return len(set(chosen) & set(wanted)) / len(wanted) if wanted else 0.0


def choose_all(name_set: str, name: str, passages: str = "rank", use_profiles: bool = True) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from src.llm.client import client_from_env
    from src.summarize import pipeline
    from src.summarize.extract import choose
    from src.summarize.refine import Model, gateway
    from src.summarize.refine.model import gateway_labeler
    from suva_data import db

    client = client_from_env("live")
    transport, labeler = gateway(client=client), gateway_labeler(client=client)
    with db.connect() as conn:
        rulings = []
        for docket in sets()[name_set]:
            rid = conn.execute("SELECT id FROM rulings WHERE docket = %s", (docket,)).fetchone()[0]
            rulings.append(pipeline.load_ruling(conn, rid))

    def one(ruling: dict) -> dict:
        model = Model(transport, budget=80, labeler=labeler)
        try:
            picked = choose.choose(ruling["text"], model, passages, use_profiles)
        except Exception as exc:  # noqa: BLE001 -- one ruling's failure is recorded, the others go on
            return {"docket": ruling["docket"], "error": f"{type(exc).__name__}: {exc}", "calls": model.calls}
        return {"docket": ruling["docket"], **picked.as_dict(), "calls": model.calls}

    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(one, rulings))
    _write(OUT / f"chosen_{name_set}_{name}.jsonl", rows)
    print(f"{len(rows)} rulings -> {OUT / f'chosen_{name_set}_{name}.jsonl'}")


def write_all(name_set: str, name: str, choice_name: str) -> None:
    """Write both fiches of each ruling from a stored choice; rows in refine_eval's format, so its `judge` and
    `report` compare them with the current pipeline's drafts (`--name` there is this run's name)."""
    from concurrent.futures import ThreadPoolExecutor

    from eval.refine_eval import OUT as REFINE_OUT
    from src.llm.client import client_from_env
    from src.summarize import pipeline
    from src.summarize.extract import candidates as cand
    from src.summarize.extract import choose, write
    from src.summarize.refine import Model, checks, gateway
    from src.summarize.refine.model import gateway_labeler
    from suva_data import db

    drafts = {(r["docket"], r["language"]): r for r in _jsonl(REFINE_OUT / f"drafts_{name_set}.jsonl")}
    stored = {r["docket"]: r for r in _jsonl(OUT / f"chosen_{name_set}_{choice_name}.jsonl")}
    client = client_from_env("live")
    transport, labeler = gateway(client=client), gateway_labeler(client=client)
    with db.connect() as conn:
        rulings = []
        for docket in sets()[name_set]:
            rid, area, language = conn.execute(
                "SELECT id, area, language FROM rulings WHERE docket = %s", (docket,)).fetchone()  # fmt: skip
            ruling = pipeline.load_ruling(conn, rid)
            ruling["language"], ruling["category"] = language, pipeline.route(area)
            rulings.append(ruling)

    def one(ruling: dict) -> list[dict]:
        row = stored.get(ruling["docket"])
        if not row or "error" in row:
            print(f"{ruling['docket']}: no choice", flush=True)
            return []
        found = cand.candidates(ruling["text"])
        chosen = tuple((found.get(item["id"]), item["role"]) for item in row["chosen"])
        picked = choose.Choice(row["point"], chosen, row["offered"], row["dropped"], row.get("scores"))
        out = []
        for lang in ("de", "fr"):
            model = Model(transport, budget=60, labeler=labeler)
            try:
                fiche = write.write_fiche(picked, lang, ruling, model)
            except Exception as exc:  # noqa: BLE001 -- one fiche's failure is reported, the others go on
                print(f"{ruling['docket']} {lang}: FAILED {type(exc).__name__}: {exc}", flush=True)
                continue
            draft = drafts.get((ruling["docket"], lang), {}).get("text", "")
            statuses = [w.status for w in fiche.sentences]
            trace = [
                {"step": "choose", "status": "passed", "calls": row.get("calls", 0), "findings": []},
                {"step": "write", "status": "needs_review" if "dropped" in statuses else "corrected",
                 "calls": fiche.calls, "findings": [{**w.as_dict(), "reason": f"{w.label} {w.role}",
                                                     "accepted": w.status == "written"} for w in fiche.sentences]},
                {"step": "flow", "status": "passed", "calls": 0,
                 "findings": [{**f, "reason": f["id"]} for f in fiche.flow]},
            ]  # fmt: skip
            out.append({
                "docket": ruling["docket"], "language": lang, "text": fiche.text, "draft": draft,
                "calls": fiche.calls + row.get("calls", 0) // 2, "trace": trace, "finish_notes": fiche.notes,
                "checks_before": checks.failing(checks.run(draft, lang, ruling["text"])) if draft else {},
                "checks_after": checks.failing(checks.run(fiche.text, lang, ruling["text"])),
                "model_log": model.log,
            })  # fmt: skip
            print(
                f"{ruling['docket']} {lang}: {fiche.calls} calls, sentences {statuses}, "
                f"flow kept {sum(f.get('accepted', False) for f in fiche.flow)}/{len(fiche.flow)}",
                flush=True,
            )
        return out

    with ThreadPoolExecutor(4) as pool:
        rows = [r for batch in pool.map(one, rulings) for r in batch]
    _write(REFINE_OUT / f"refined_{name_set}_{name}.jsonl", rows)
    print(f"{len(rows)} fiches -> {REFINE_OUT / f'refined_{name_set}_{name}.jsonl'}")


def report(name_set: str, name: str) -> dict:
    golds = {r["docket"]: r for r in _jsonl(OUT / f"gold_{name_set}.jsonl")}
    chosen = {r["docket"]: r for r in _jsonl(OUT / f"chosen_{name_set}_{name}.jsonl")}
    from src.summarize.extract import candidates as cand  # noqa: F401 -- labels come from the stored rows

    sent, cons, rand, sizes, soft, ranked, errors = [], [], [], [], [], [], 0
    rng = random.Random(0)
    for docket, g in golds.items():
        if not g["gold"] or not g["gold"]["kept"]:
            continue
        row = chosen.get(docket)
        if row is None or "error" in row:
            errors += 1
            sent.append(0.0), cons.append(0.0)
            continue
        ids = [item["id"] for item in row["chosen"]]
        labels = {item["label"] for item in row["chosen"]}
        sizes.append(len(ids))
        sent.append(recall(ids, g["gold"]["kept"]))
        picked = [words(item["text"]) for item in row["chosen"]]
        hits = [
            max((len(words(s) & p) / max(1, len(words(s))) for p in picked), default=0) >= SOFT
            for s in g["gold"]["texts"]
        ]
        soft.append(sum(hits) / len(hits))
        if row.get("scores"):
            ranked.append(len(set(top_labels(row["scores"])) & set(g["gold"]["labels"])) / len(g["gold"]["labels"]))
        cons.append(len(labels & set(g["gold"]["labels"])) / len(g["gold"]["labels"]))
        pool = [f"S{i}" for i in range(1, g["candidates"] + 1)]
        rand.append(statistics.mean(recall(rng.sample(pool, min(len(ids), len(pool))), g["gold"]["kept"])
                                    for _ in range(200)))  # fmt: skip
    summary = {
        "set": name_set,
        "name": name,
        "rulings_scored": len(sent),
        "errors": errors,
        "chosen_median": statistics.median(sizes) if sizes else None,
        "sentence_recall": round(statistics.mean(sent), 3) if sent else None,
        "consideration_recall": round(statistics.mean(cons), 3) if cons else None,
        "soft_sentence_recall": round(statistics.mean(soft), 3) if soft else None,
        "ranked_consideration_recall": round(statistics.mean(ranked), 3) if ranked else None,
        "random_sentence_recall": round(statistics.mean(rand), 3) if rand else None,
        "per_ruling": [
            {"docket": d, "sentence_recall": round(s, 2), "consideration_recall": round(c, 2)}
            for d, s, c in zip(
                [d for d, g in golds.items() if g["gold"] and g["gold"]["kept"]], sent, cons, strict=False
            )
        ],  # fmt: skip
        "bars": BARS,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("filter", "choose", "write", "report"))
    parser.add_argument("--set", default="iterate", choices=("iterate", "holdout"))
    parser.add_argument("--name", default="c1")
    parser.add_argument("--passages", default="rank", choices=("rank", "list"))
    parser.add_argument("--no-profiles", action="store_true", help="choose without the profiles (profiles.py)")
    parser.add_argument("--choice", default="c6", help="the stored choice a `write` run starts from")
    args = parser.parse_args(argv)
    from src.summarize import summarize

    summarize.load_env()
    results = ROOT / "results"
    if args.command == "filter":
        summary = filter_report(args.set)
        (results / f"extract_filter_{args.set}.json").write_text(json.dumps(summary, indent=2) + "\n")
    elif args.command == "choose":
        choose_all(args.set, args.name, args.passages, not args.no_profiles)
        return 0
    elif args.command == "write":
        write_all(args.set, args.name, args.choice)
        return 0
    else:
        summary = report(args.set, args.name)
        (results / f"extract_eval_{args.set}_{args.name}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("per_ruling", "bars")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

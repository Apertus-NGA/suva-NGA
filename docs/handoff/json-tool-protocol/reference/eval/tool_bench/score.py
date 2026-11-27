# SPDX-License-Identifier: Apache-2.0
# AST-style scoring (multiset of tool name + normalised required arguments) follows ArchAI's tool_bench
# (kirtanp/hackpertus-archives, src/archai/tool_bench.py), Copyright (c) 2026 The ArchAI contributors,
# MIT License, itself modelled on the Berkeley Function Calling Leaderboard. Added here: raw vs
# validated scoring, id fidelity, Wilson intervals, paired bootstrap, thresholds. See NOTICE.
"""Scoring, aggregation, comparison and acceptance thresholds of the tool benchmark.

A row is one (model, configuration, case, repetition). Two scores per row:

* ``exact_raw``: the calls **as the model wrote them** equal the gold multiset (ids must be the
  offered canonical ids, acts the canonical German abbreviation). This is what a system without
  our validation layer would get.
* ``exact``: the calls **after** the protocol's validation (exact id resolution, act aliases,
  refusal of invalid calls), and after the form tools' single repair turn. This is what the
  pipeline gets.
* ``exact_first``: like ``exact``, on the **first reply only** (no repair turn). Native calls get
  no repair turn, so every native-vs-JSON comparison and the decision rule use ``exact_first``.

Irrelevance cases are scored on what the model emitted: correct only if it emitted **no call** at
all (a call that validation refused still counts as a call).

Statistics: Wilson intervals for proportions; a paired bootstrap that resamples **cases** (all
repetitions of a case move together, because they are not independent), 10,000 draws (EVAL §1.5);
thresholds evaluated on each repetition, the worst one counts (EVAL §1.4).

Usage::

    python -m eval.tool_bench.score results/tool_bench/<run>/rows.jsonl            # report
    python -m eval.tool_bench.score --compare <baseline rows> <candidate rows>       # non-regression
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .tools import norm_article, norm_docket

THRESHOLDS = Path(__file__).with_name("thresholds.json")


def _n(v: Any) -> str:
    return unicodedata.normalize("NFKC", str(v)).strip().casefold()


def canon_call(name: Any, args: Any) -> tuple[str, str]:
    """A hashable form of one call: tool name and its arguments, lightly normalised (case, spaces).

    Normalisation never maps one id onto another: ``E. 4.2`` stays ``e. 4.2`` and does not equal
    ``c7``. Dockets and article numbers get their format normalised (``8C 1/2025`` = ``8C_1/2025``,
    ``Art. 6`` = ``6``) because the format is not what the benchmark measures.
    """
    a = dict(args) if isinstance(args, Mapping) else {}
    keep: dict[str, Any] = {}
    for k, v in sorted(a.items()):
        if k == "a_docket" and isinstance(v, str):
            keep[k] = norm_docket(v)
        elif k == "b_number" and isinstance(v, (str, int)):
            keep[k] = norm_article(str(v))
        else:
            keep[k] = sorted(_n(x) for x in v) if isinstance(v, list) else _n(v)
    return str(name), json.dumps(keep, sort_keys=True, ensure_ascii=False)


def score_calls(gold: Sequence[Sequence[Any]], got: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """Exact match, precision and recall of a list of calls against the gold list (multisets)."""
    g = Counter(canon_call(n, a) for n, a in gold)
    o = Counter(canon_call(n, a) for n, a in got)
    tp = sum((g & o).values())
    return {"exact": g == o,
            "precision": tp / sum(o.values()) if o else (1.0 if not g else 0.0),
            "recall": tp / sum(g.values()) if g else (1.0 if not o else 0.0)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval of a proportion (95 % by default). ``(0, 1)`` when ``n == 0``."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def paired_bootstrap(a: Mapping[Any, float], b: Mapping[Any, float], *, n: int = 10_000,
                     seed: int = 0) -> tuple[float, float, float, int]:
    """Mean of ``b - a`` over the keys both share, with a 95 % percentile **cluster** bootstrap interval.

    Keys are ``(case_id, rep)``: the same case under two configurations (or two runs), so the
    comparison is paired. The bootstrap resamples case ids and keeps all repetitions of a drawn case
    together: repetitions of one case are correlated, and resampling them as independent pairs
    would narrow the interval (a duplicated run must not look more significant). Keys that are not
    tuples are their own cluster. Returns ``(diff, low, high, n_pairs)``.
    """
    keys = sorted(set(a) & set(b), key=str)
    if not keys:
        return 0.0, 0.0, 0.0, 0
    sums: dict[Any, float] = defaultdict(float)
    counts: dict[Any, int] = defaultdict(int)
    for k in keys:
        cluster = k[0] if isinstance(k, tuple) else k
        sums[cluster] += float(b[k]) - float(a[k])
        counts[cluster] += 1
    clusters = sorted(sums, key=str)
    s_list = [sums[c] for c in clusters]
    c_list = [counts[c] for c in clusters]
    m = len(clusters)
    rnd = random.Random(seed)
    means = []
    for _ in range(n):
        idx = [rnd.randrange(m) for _ in range(m)]
        means.append(sum(s_list[i] for i in idx) / sum(c_list[i] for i in idx))
    means.sort()
    return sum(s_list) / len(keys), means[int(0.025 * n)], means[int(0.975 * n) - 1], len(keys)


def _group(rows: Iterable[Mapping[str, Any]], keys: Sequence[str]) -> dict[tuple, list[Mapping[str, Any]]]:
    out: dict[tuple, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        out[tuple(r[k] for k in keys)].append(r)
    return dict(out)


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics of a group of rows."""
    n = len(rows)
    k = sum(bool(r["exact"]) for r in rows)
    lo, hi = wilson(k, n)
    text = [r for r in rows if r.get("text_exact") is not None]
    ids_out = sum(r.get("ids_emitted", 0) for r in rows)
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    return {
        "n": n,
        "exact": round(k / n, 3) if n else None,
        "exact_ci95": [round(lo, 3), round(hi, 3)],
        "exact_first": round(sum(bool(r.get("exact_first", r["exact"])) for r in rows) / n, 3) if n else None,
        "exact_raw": round(sum(bool(r["exact_raw"]) for r in rows) / n, 3) if n else None,
        "valid": round(sum(bool(r["valid"]) for r in rows) / n, 3) if n else None,
        "repaired": sum(bool(r.get("repaired")) for r in rows),
        "invented_id_rate": round(sum(r.get("invented_ids", 0) for r in rows) / ids_out, 4) if ids_out else 0.0,
        "noncanonical_id_rate": round(sum(r.get("noncanonical_ids", 0) for r in rows) / ids_out, 4) if ids_out else 0.0,
        "accepted_invalid_ids": sum(r.get("accepted_invalid_ids", 0) for r in rows),
        "unknown_tools": sum(r.get("unknown_tools", 0) for r in rows),
        "request_errors": sum(bool(r.get("request_error")) for r in rows),
        "leaked_tool_text": sum(bool(r.get("leaked_tool_text")) for r in rows),
        "answered_in_text": len(text),
        "text_answer_correct": sum(bool(r["text_exact"]) for r in text),
        "latency_median_s": round(statistics.median(lat), 2) if lat else None,
        "latency_p95_s": round(sorted(lat)[max(0, math.ceil(0.95 * len(lat)) - 1)], 2) if lat else None,
    }


def report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per (model, config): overall, by category, by language, by category x language."""
    out: dict[str, Any] = {}
    for (model, config), rs in sorted(_group(rows, ["model", "config"]).items()):
        out[f"{model} / {config}"] = {
            "overall": metrics(rs),
            "by_category": {c: metrics(g) for (c,), g in sorted(_group(rs, ["category"]).items())},
            "by_language": {lang: metrics(g) for (lang,), g in sorted(_group(rs, ["lang"]).items())},
            "by_category_language": {f"{c}/{lang}": metrics(g)
                                     for (c, lang), g in sorted(_group(rs, ["category", "lang"]).items())},
        }
    return out


def compare_configs(rows: Sequence[Mapping[str, Any]], base: str, other: str, *,
                    category: str | None = None, metric: str = "exact_first") -> dict[str, Any]:
    """Paired difference of ``metric`` between two configurations (``other - base``).

    One entry per model (``"<model>"``, all languages) and per model and language
    (``"<model> / <lang>"``). ``exact_first`` by default: native calls get no repair turn.
    """
    out = {}
    sel = [r for r in rows if category is None or r["category"] == category]
    groups = {**{(m,): g for (m,), g in _group(sel, ["model"]).items()}, **_group(sel, ["model", "lang"])}
    for key, rs in sorted(groups.items()):
        a = {(r["case_id"], r["rep"]): r.get(metric, r["exact"]) for r in rs if r["config"] == base}
        b = {(r["case_id"], r["rep"]): r.get(metric, r["exact"]) for r in rs if r["config"] == other}
        diff, lo, hi, n = paired_bootstrap(a, b)
        n_cases = len({k[0] for k in set(a) & set(b)})
        out[" / ".join(key)] = {"metric": metric, "diff": round(diff, 3), "ci95": [round(lo, 3), round(hi, 3)],
                                "pairs": n, "cases": n_cases}
    return out


def decide(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate the pre-registered decision rule of ``thresholds.json`` (native vs JSON).

    Returns ``{"verdict": ..., "per_language": {...}}``. The verdict is ``keep_json`` unless every
    language reaches ``min_cases`` and shows the required paired gain with an interval above 0; then
    it is ``native_candidate``, which still needs the portability check on the judges' endpoint.
    ``insufficient_n`` when a language has too few cases to decide.
    """
    spec = spec or json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    rule = spec["decision_rule"]["computed"]
    sel = [r for r in rows if rule["model"].lower() in r["model"].lower()]
    cmp_ = compare_configs(sel, rule["base"], rule["challenger"], category=rule["category"], metric=rule["metric"])
    per_lang = {k.split(" / ")[1]: v for k, v in cmp_.items() if " / " in k}
    if any(per_lang.get(lang, {}).get("cases", 0) < rule["min_cases_per_language"] for lang in rule["languages"]):
        verdict = "insufficient_n"  # JSON stays by default; the rule cannot be applied
    elif all(per_lang[lang]["diff"] >= rule["min_gain"] and per_lang[lang]["ci95"][0] > 0
             for lang in rule["languages"]):
        verdict = "native_candidate"
    else:
        verdict = "keep_json"
    return {"verdict": verdict, "rule": spec["decision_rule"]["rule"], "per_language": per_lang}


def compare_runs(baseline: Sequence[Mapping[str, Any]], candidate: Sequence[Mapping[str, Any]], *,
                 tolerance: float = 0.05, min_cases: int = 20) -> dict[str, Any]:
    """Non-regression: per (model, config, category), candidate minus baseline on the same cases.

    Both runs must hold the same (model, config, category, case, repetition) keys, that is the same
    profile on the same rulings with the same seed; otherwise the result lists them under
    ``not_comparable`` and the CLI exits 2. A group **regresses** when the paired cluster-bootstrap
    interval of ``exact`` lies entirely below zero. A point drop larger than ``tolerance`` whose
    interval still includes zero is listed under ``watch`` (noise is likely: the 70B is not
    deterministic, K10), and so is any group with fewer than ``min_cases`` cases.
    """
    out: dict[str, Any] = {"groups": {}, "regressions": [], "watch": [], "not_comparable": []}
    gb = _group(baseline, ["model", "config", "category"])
    gc = _group(candidate, ["model", "config", "category"])
    for key in sorted(set(gb) | set(gc)):
        name = " / ".join(key)
        a = {(r["case_id"], r["rep"]): r["exact"] for r in gb.get(key, [])}
        b = {(r["case_id"], r["rep"]): r["exact"] for r in gc.get(key, [])}
        if set(a) != set(b):
            out["not_comparable"].append({"group": name, "only_in_baseline": len(set(a) - set(b)),
                                          "only_in_candidate": len(set(b) - set(a))})
            continue
        diff, lo, hi, n = paired_bootstrap(a, b)
        n_cases = len({k[0] for k in a})
        out["groups"][name] = {"diff": round(diff, 3), "ci95": [round(lo, 3), round(hi, 3)], "pairs": n,
                               "cases": n_cases}
        if hi < 0:
            out["regressions"].append(name)
        elif diff < -tolerance or n_cases < min_cases:
            out["watch"].append(name)
    return out


_OPS: dict[str, Callable[[float, float], bool]] = {">=": lambda x, y: x >= y, "<=": lambda x, y: x <= y,
                                                    "==": lambda x, y: x == y}


def _allowed(filt: Mapping[str, Any], key: str, value: str) -> bool:
    want = filt.get(key)
    return not want or value in ([want] if isinstance(want, str) else want)


def check_thresholds(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Evaluate the pre-registered criteria of ``thresholds.json`` on a run. One result per group.

    Each criterion is evaluated on every repetition separately and the **worst** repetition counts
    (EVAL §1.4: a guard must hold on each run, not on the average). ``value_by_rep`` keeps them all.
    """
    spec = spec or json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    results = []
    for crit in spec["criteria"]:
        f = crit.get("filter", {})
        sel = [r for r in rows if (not f.get("model") or f["model"].lower() in r["model"].lower())
               and _allowed(f, "config", r["config"]) and _allowed(f, "category", r["category"])]
        groups = _group(sel, [crit["group_by"]]) if crit.get("group_by") else {("all",): sel}
        if not groups:
            results.append({"id": crit["id"], "group": None, "value": None, "pass": False, "note": "no rows",
                            "blocking": crit.get("blocking", True)})
        op = _OPS[crit["op"]]
        for gkey, g in sorted(groups.items()):
            by_rep = {}
            for (rep_i,), gr in sorted(_group(g, ["rep"]).items()):
                m = metrics(gr)
                by_rep[rep_i] = m["exact_ci95"][0] if crit["metric"] == "exact_wilson_low" else m[crit["metric"]]
            failing = [v for v in by_rep.values() if v is None or not op(v, crit["value"])]
            if failing:
                value = failing[0]
            elif crit["op"] == ">=":
                value = min(by_rep.values())
            elif crit["op"] == "<=":
                value = max(by_rep.values())
            else:
                value = next(iter(by_rep.values()))
            results.append({"id": crit["id"], "group": gkey[0], "n": len(g), "reps": len(by_rep),
                            "metric": crit["metric"], "value": value, "value_by_rep": by_rep, "op": crit["op"],
                            "target": crit["value"], "pass": not failing, "blocking": crit.get("blocking", True)})
    return results


def _read(path: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: print the report and the threshold checks, or compare two runs.

    Exit 1 on a failed blocking threshold or a regression; 2 when two runs do not hold the same cases.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rows", nargs="+", help="rows.jsonl (one), or baseline and candidate with --compare")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args(argv)
    if args.compare:
        res = compare_runs(_read(args.rows[0]), _read(args.rows[1]))
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 2 if res["not_comparable"] else 1 if res["regressions"] else 0
    rows = _read(args.rows[0])
    checks = check_thresholds(rows)
    print(json.dumps({"report": report(rows), "thresholds": checks, "decision": decide(rows)}, indent=1,
                     ensure_ascii=False))
    return 1 if any(not c["pass"] and c.get("blocking", True) for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())

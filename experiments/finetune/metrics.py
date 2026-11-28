"""Layer-2 metrics on suva-ft-v3, frozen before the benchmark run (docs/FINETUNE.md §5).

One module for every layer-2 table, so the rule, the zero-shot models and a later LoRA are measured the same way.
Standard library only.

Population: the two complete test quarters of suva-ft-v3 (fold_A test = 2026Q1, fold_B test = 2025Q4).
A system is one score per ruling for both quarters (higher = more relevant).

Primary metrics (pooled over both quarters, paired bootstrap 95 % CI):
1. AUC vs hard negatives: the 59 positives against the 235 hard negatives, raw scores pooled.
2. F2 at the transferred threshold: the threshold that maximises F2 on one quarter is applied to the other
   (ties: the lowest such threshold); TP and FP are summed over both quarters. Two variants: on the full quarter,
   and after layer 1 (a ruling is flagged only if `couche1` and score >= threshold; the threshold is learnt on the
   other quarter's `couche1` rulings; positives dropped by layer 1 count as misses).
3. F2 and recall of a fixed-size list: the top k per quarter (k = 45, 60); pooled = both lists together (2k
   rulings). A tie at the cut counts its expected share of positives (random order inside the tie).

Bootstrap: resampling with replacement inside each quarter and each stratum (positive, hard negative, easy
negative), so the counts per stratum stay fixed. Every system is measured on the same resamples, so differences
between systems are paired. Thresholds are re-learnt on every resample (the CI includes threshold selection).
Weights: a resample is a vector of counts per ruling; every metric accepts weights, and weight 1 everywhere is the
point estimate.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

DATASET = "suva-ft-v3"
IDS_DIGEST = "69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6"
AMBIGUOUS_SHA256 = "4931d15a44d57fd2982c9cd3a22e583f727899e835dd1f98f3613993c4d21a7c"
QUARTERS = ("2026Q1", "2025Q4")  # fold_A test, fold_B test
FOLD_OF = {"2026Q1": "fold_A", "2025Q4": "fold_B"}
TOP_K = (45, 60)
N_BOOT = 1000
SEED = 20261127


class MetricsError(ValueError):
    """Inputs that cannot be measured honestly (missing score, unknown id, wrong file)."""


# -- population -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Ruling:
    decision_id: str
    docket: str
    quarter: str
    y: bool
    kind: str  # positive | hard_negative | easy_negative
    lang: str
    matiere: str
    couche1: bool


@dataclass
class Population:
    rows: dict[str, list[Ruling]]  # quarter -> rulings in file order (the canonical order)
    index: dict[str, tuple[str, int]] = field(init=False)

    def __post_init__(self) -> None:
        self.index = {}
        for q, rows in self.rows.items():
            for i, r in enumerate(rows):
                if r.decision_id in self.index:
                    raise MetricsError(f"duplicate decision_id {r.decision_id}")
                self.index[r.decision_id] = (q, i)

    def without(self, dockets: set[str]) -> Population:
        """The same population minus some rulings (sensitivity analysis). Fails if a docket is unknown."""
        known = {r.docket for rows in self.rows.values() for r in rows}
        unknown = dockets - known
        if unknown:
            raise MetricsError(f"{len(unknown)} dockets to exclude are not in the population")
        return Population({q: [r for r in rows if r.docket not in dockets] for q, rows in self.rows.items()})

    def counts(self) -> dict[str, dict[str, int]]:
        return {q: {k: sum(r.kind == k for r in rows) for k in ("positive", "hard_negative", "easy_negative")}
                for q, rows in self.rows.items()}


def load_population(data_root: str | Path) -> Population:
    """The test splits of suva-ft-v3. Run verify_dataset.py first: this function does not check hashes."""
    rows: dict[str, list[Ruling]] = {}
    for q in QUARTERS:
        path = Path(data_root) / FOLD_OF[q] / "test.jsonl"
        out = []
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            ex = json.loads(line)
            m = ex["meta"]
            label = ex["completion"][0]["content"]
            if m["quarter"] != q:
                raise MetricsError(f"{m['decision_id']}: quarter {m['quarter']} in {path}")
            if (label == "Ja") != (m["kind"] == "positive"):
                raise MetricsError(f"{m['decision_id']}: label {label} and kind {m['kind']} disagree")
            out.append(Ruling(m["decision_id"], m["docket"], q, label == "Ja", m["kind"], m["lang"], m["matiere"],
                              bool(m["couche1"])))
        rows[q] = out
    return Population(rows)


def load_ambiguous(path: str | Path, expected_sha256: str = AMBIGUOUS_SHA256) -> set[str]:
    """Dockets of the 25 ambiguous UV-merit negatives (audit finding M1); checks the file hash."""
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != expected_sha256:
        raise MetricsError(f"ambiguous-negatives list: SHA-256 {got[:12]}… is not {expected_sha256[:12]}…")
    return {r["docket"] for r in csv.DictReader(Path(path).open(encoding="utf-8"))}


# -- scores ------------------------------------------------------------------------------------------------------
def rule_score(f: dict) -> float:
    """The audit's 3-signal rule, no LLM (experiments/finetune/audit/a07_rule_minimal.py, unchanged):
    2 x [UV or MV] + 1 x [IV] + 1 x [not inadmissible] + length (chars capped at 60,000) / 1e6."""
    return 2 * (f["matiere"] in ("UV", "MV")) + (f["matiere"] == "IV") + (not f["irrecevable"]) + min(
        f["chars"], 60000
    ) / 1e6


def load_rule_scores(features_path: str | Path) -> dict[str, float]:
    """Rule scores from the audit's a02 features (a02_features.json.gz)."""
    opener = gzip.open if str(features_path).endswith(".gz") else open
    with opener(features_path, "rt", encoding="utf-8") as fh:
        feats = json.load(fh)
    return {did: rule_score(f) for did, f in feats.items()}


def load_scores_jsonl(path: str | Path) -> dict[str, float]:
    """`decision_id` -> `score` from a scores file. A missing score or a duplicate fails (no silent drop)."""
    out: dict[str, float] = {}
    for n, line in enumerate(Path(path).open(encoding="utf-8"), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("score") is None:
            raise MetricsError(f"{path}:{n}: {r.get('decision_id')} has no score")
        if r["decision_id"] in out:
            raise MetricsError(f"{path}:{n}: duplicate {r['decision_id']}")
        out[r["decision_id"]] = float(r["score"])
    return out


def rank_average(pop: Population, parts: list[dict[str, float]]) -> dict[str, float]:
    """Equal-weight mean of within-quarter percentile ranks (rank / n in (0, 1]; ties get their average rank).
    The combination of FT-Q3 (docs/FINETUNE.md §6b): no weight is fitted."""
    if not parts:
        raise MetricsError("rank_average needs at least one score dict")
    out: dict[str, float] = {}
    for rows in pop.rows.values():
        ids = [r.decision_id for r in rows]
        n = len(ids)
        acc = dict.fromkeys(ids, 0.0)
        for s in parts:
            missing = [d for d in ids if d not in s]
            if missing:
                raise MetricsError(f"rank_average: {len(missing)} rulings without a score")
            order = sorted(ids, key=lambda d, s=s: s[d])
            i = 0
            while i < n:
                j = i
                while j < n and s[order[j]] == s[order[i]]:
                    j += 1
                pct = (i + j + 1) / 2 / n  # average 1-based rank of the tie group, over n
                for k in range(i, j):
                    acc[order[k]] += pct / len(parts)
                i = j
        out.update(acc)
    return out


# -- a system prepared on a population ---------------------------------------------------------------------------
@dataclass
class _Sorted:
    order: list[int]  # canonical indices, by score descending (stable)
    scores: list[float]  # scores in that order
    groups: list[tuple[int, int]]  # runs of equal score: [start, end)


def _sort(idx: Iterable[int], score_of: Callable[[int], float]) -> _Sorted:
    order = sorted(idx, key=lambda i: -score_of(i))
    s = [score_of(i) for i in order]
    groups, a = [], 0
    for b in range(1, len(s) + 1):
        if b == len(s) or s[b] != s[a]:
            groups.append((a, b))
            a = b
    return _Sorted(order, s, groups)


@dataclass
class System:
    name: str
    scores: dict[str, float]
    pop: Population
    by_q: dict[str, _Sorted] = field(init=False)
    pos_hard: _Sorted = field(init=False)  # positives and hard negatives of both quarters (index into _flat)
    _flat: list[tuple[str, int]] = field(init=False)

    def __post_init__(self) -> None:
        need = set(self.pop.index)
        missing = need - set(self.scores)
        if missing:
            raise MetricsError(f"{self.name}: {len(missing)} rulings without a score (e.g. {sorted(missing)[0]})")
        bad = [d for d in need if not math.isfinite(self.scores[d])]
        if bad:
            raise MetricsError(f"{self.name}: non-finite score for {len(bad)} rulings")
        self.by_q = {}
        for q, rows in self.pop.rows.items():
            self.by_q[q] = _sort(range(len(rows)), lambda i, rows=rows: self.scores[rows[i].decision_id])
        self._flat = [(q, i) for q in QUARTERS for i, r in enumerate(self.pop.rows[q]) if r.kind != "easy_negative"]
        self.pos_hard = _sort(range(len(self._flat)),
                              lambda j: self.scores[self.pop.rows[self._flat[j][0]][self._flat[j][1]].decision_id])


Weights = dict[str, list[int]]  # quarter -> count per canonical ruling


def unit_weights(pop: Population) -> Weights:
    return {q: [1] * len(rows) for q, rows in pop.rows.items()}


def f2_score(tp: float, fp: float, npos: float) -> float:
    if tp <= 0 or npos <= 0:
        return 0.0
    p, r = tp / (tp + fp), tp / npos
    return 5 * p * r / (4 * p + r)


def auc_weighted(srt: _Sorted, is_pos: Callable[[int], bool], weight: Callable[[int], int]) -> float | None:
    """Mann-Whitney AUC over rows sorted by score descending; ties count one half."""
    wp = sum(weight(i) for i in srt.order if is_pos(i))
    wn = sum(weight(i) for i in srt.order if not is_pos(i))
    if wp == 0 or wn == 0:
        return None
    above_n, acc = 0, 0.0
    for a, b in srt.groups:
        gp = sum(weight(srt.order[k]) for k in range(a, b) if is_pos(srt.order[k]))
        gn = sum(weight(srt.order[k]) for k in range(a, b) if not is_pos(srt.order[k]))
        acc += gp * (wn - above_n - gn) + 0.5 * gp * gn
        above_n += gn
    return acc / (wp * wn)


def best_threshold(sys_: System, q: str, w: Weights, layer1: bool) -> tuple[float | None, float]:
    """Threshold maximising F2 on quarter q (candidates: scores present with weight > 0; ties: the lowest)."""
    rows, wq, srt = sys_.pop.rows[q], w[q], sys_.by_q[q]
    npos = sum(wq[i] for i, r in enumerate(rows) if r.y)
    tp = fp = 0
    best_f, best_t = -1.0, None
    for a, b in srt.groups:
        seen = False
        for k in range(a, b):
            i = srt.order[k]
            if wq[i] == 0 or (layer1 and not rows[i].couche1):
                continue
            seen = True
            if rows[i].y:
                tp += wq[i]
            else:
                fp += wq[i]
        if seen:
            f = f2_score(tp, fp, npos)
            if f >= best_f:
                best_f, best_t = f, srt.scores[a]
    return best_t, max(best_f, 0.0)


@dataclass
class Flagged:
    tp: float
    fp: float
    npos: float
    found: dict[int, float]  # canonical index of each positive -> share flagged (1, 0, or a tie share)


def flagged_at(sys_: System, q: str, w: Weights, t: float | None, layer1: bool) -> Flagged:
    rows, wq, srt = sys_.pop.rows[q], w[q], sys_.by_q[q]
    npos = sum(wq[i] for i, r in enumerate(rows) if r.y)
    tp = fp = 0
    found = {i: 0.0 for i, r in enumerate(rows) if r.y}
    if t is not None:
        for k, i in enumerate(srt.order):
            if srt.scores[k] < t:
                break
            if wq[i] == 0 or (layer1 and not rows[i].couche1):
                continue
            if rows[i].y:
                tp += wq[i]
                found[i] = 1.0
            else:
                fp += wq[i]
    return Flagged(tp, fp, npos, found)


def top_k(sys_: System, q: str, w: Weights, k: int) -> Flagged:
    """The k highest-scored rulings of quarter q; a tie at the cut contributes its expected share."""
    rows, wq, srt = sys_.pop.rows[q], w[q], sys_.by_q[q]
    npos = sum(wq[i] for i, r in enumerate(rows) if r.y)
    found = {i: 0.0 for i, r in enumerate(rows) if r.y}
    left, tp = k, 0.0
    for a, b in srt.groups:
        if left <= 0:
            break
        members = [srt.order[j] for j in range(a, b) if wq[srt.order[j]] > 0]
        gw = sum(wq[i] for i in members)
        if gw == 0:
            continue
        share = 1.0 if gw <= left else left / gw
        for i in members:
            if rows[i].y:
                tp += wq[i] * share
                found[i] = share
        left -= min(gw, left)
    return Flagged(tp, k - tp, npos, found)


def _recall_by(sys_: System, flagged: dict[str, Flagged], w: Weights, attr: str) -> dict[str, float | None]:
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    for q, fl in flagged.items():
        rows = sys_.pop.rows[q]
        for i, share in fl.found.items():
            g = getattr(rows[i], attr)
            num[g] = num.get(g, 0.0) + w[q][i] * share
            den[g] = den.get(g, 0.0) + w[q][i]
    return {g: (num[g] / den[g] if den[g] else None) for g in sorted(den)}


def _other(q: str) -> str:
    return QUARTERS[1] if q == QUARTERS[0] else QUARTERS[0]


def measure(sys_: System, w: Weights | None = None) -> dict:
    """Every metric of one system on one (re)sample. Keys are flat strings so the bootstrap can pair them."""
    w = w or unit_weights(sys_.pop)
    out: dict[str, float | None] = {}
    flat = sys_._flat

    def ph_pos(j: int) -> bool:
        return sys_.pop.rows[flat[j][0]][flat[j][1]].y

    def ph_w(j: int) -> int:
        return w[flat[j][0]][flat[j][1]]

    out["auc_hard_pooled"] = auc_weighted(sys_.pos_hard, ph_pos, ph_w)
    for q in QUARTERS:
        rows, srt = sys_.pop.rows[q], sys_.by_q[q]
        ph_q = _sort([i for i, r in enumerate(rows) if r.kind != "easy_negative"],
                     lambda i, rows=rows: sys_.scores[rows[i].decision_id])
        out[f"auc_hard_{q}"] = auc_weighted(ph_q, lambda i, rows=rows: rows[i].y, lambda i, q=q: w[q][i])
        out[f"auc_full_{q}"] = auc_weighted(srt, lambda i, rows=rows: rows[i].y, lambda i, q=q: w[q][i])
    for variant, layer1 in (("full", False), ("l1", True)):
        fl = {}
        for q in QUARTERS:
            t, _ = best_threshold(sys_, _other(q), w, layer1)
            fl[q] = flagged_at(sys_, q, w, t, layer1)
            out[f"thr_tr_{variant}_{q}"] = t
            out[f"f2_tr_{variant}_{q}"] = f2_score(fl[q].tp, fl[q].fp, fl[q].npos)
            out[f"tp_tr_{variant}_{q}"], out[f"fp_tr_{variant}_{q}"] = fl[q].tp, fl[q].fp
        tp, fp, npos = (sum(getattr(f, a) for f in fl.values()) for a in ("tp", "fp", "npos"))
        out[f"f2_tr_{variant}_pooled"] = f2_score(tp, fp, npos)
        out[f"recall_tr_{variant}_pooled"] = tp / npos if npos else None
        out[f"tp_tr_{variant}_pooled"], out[f"fp_tr_{variant}_pooled"] = tp, fp
        if variant == "full":
            for attr in ("matiere", "lang"):
                for g, v in _recall_by(sys_, fl, w, attr).items():
                    out[f"recall_tr_full_{attr}_{g}"] = v
    for k in TOP_K:
        fl = {q: top_k(sys_, q, w, k) for q in QUARTERS}
        for q in QUARTERS:
            out[f"f2_top{k}_{q}"] = f2_score(fl[q].tp, fl[q].fp, fl[q].npos)
            out[f"tp_top{k}_{q}"] = fl[q].tp
        tp, npos = sum(f.tp for f in fl.values()), sum(f.npos for f in fl.values())
        out[f"f2_top{k}_pooled"] = f2_score(tp, 2 * k - tp, npos)
        out[f"recall_top{k}_pooled"] = tp / npos if npos else None
        out[f"tp_top{k}_pooled"] = tp
        if k == max(TOP_K):
            for attr in ("matiere", "lang"):
                for g, v in _recall_by(sys_, fl, w, attr).items():
                    out[f"recall_top{k}_{attr}_{g}"] = v
    return out


# -- paired bootstrap --------------------------------------------------------------------------------------------
def resample_weights(pop: Population, rng: random.Random) -> Weights:
    w: Weights = {}
    for q, rows in pop.rows.items():
        wq = [0] * len(rows)
        for kind in ("positive", "hard_negative", "easy_negative"):
            stratum = [i for i, r in enumerate(rows) if r.kind == kind]
            for _ in stratum:
                wq[rng.choice(stratum)] += 1
        w[q] = wq
    return w


def percentile_ci(values: list[float], level: float = 0.95) -> tuple[float, float] | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    lo = int(math.floor((1 - level) / 2 * len(v)))
    hi = int(math.ceil((1 + level) / 2 * len(v))) - 1
    return v[lo], v[min(hi, len(v) - 1)]


def paired_bootstrap(systems: list[System], n_boot: int = N_BOOT, seed: int = SEED) -> list[dict[str, dict]]:
    """One dict per resample: system name -> measure(). Every system sees the same resampled rulings."""
    pops = {id(s.pop) for s in systems}
    if len(pops) != 1:
        raise MetricsError("paired bootstrap needs every system on the same population object")
    rng = random.Random(seed)
    pop = systems[0].pop
    out = []
    for _ in range(n_boot):
        w = resample_weights(pop, rng)
        out.append({s.name: measure(s, w) for s in systems})
    return out


def summarise(systems: list[System], boots: list[dict[str, dict]], keys: Iterable[str],
              pairs: Iterable[tuple[str, str]]) -> dict:
    """Point estimate + CI per system and metric; paired difference CI per pair (a minus b)."""
    keys = list(keys)
    res: dict = {"systems": {}, "pairs": {}, "n_boot": len(boots)}
    for s in systems:
        point = measure(s)
        res["systems"][s.name] = {k: {"point": point.get(k), "ci95": percentile_ci([b[s.name].get(k) for b in boots])}
                                  for k in keys}
    for a, b in pairs:
        pa, pb = (measure(next(s for s in systems if s.name == n)) for n in (a, b))
        res["pairs"][f"{a} - {b}"] = {}
        for k in keys:
            diffs = [bt[a][k] - bt[b][k] for bt in boots if bt[a].get(k) is not None and bt[b].get(k) is not None]
            point = pa[k] - pb[k] if pa.get(k) is not None and pb.get(k) is not None else None
            ci = percentile_ci(diffs)
            res["pairs"][f"{a} - {b}"][k] = {
                "point": point, "ci95": ci,
                "share_above_0": sum(d > 0 for d in diffs) / len(diffs) if diffs else None,
                "ci_strictly_above_0": bool(ci and ci[0] > 0),
                "ci_strictly_below_0": bool(ci and ci[1] < 0),
            }
    return res


# -- repeated runs -----------------------------------------------------------------------------------------------
def repetition_report(pop: Population, reps: list[dict[str, float]], base: dict[str, float], name: str,
                      thresholds: dict[str, float | None]) -> dict:
    """Spread of repeated runs on a subset (e.g. positives + hard negatives).

    `reps`: one dict per repetition, decision_id -> score, all on the same subset.
    `base`: a full pass, used for the rulings outside the subset, so full-quarter metrics (F2, top-k) can be
    computed per repetition. AUC vs hard needs no base. `thresholds`: quarter -> fixed threshold (the full pass's
    transferred threshold) at which flips are counted.
    """
    if not reps:
        raise MetricsError("no repetition")
    subset = set(reps[0])
    if any(set(r) != subset for r in reps):
        raise MetricsError("repetitions cover different rulings")
    per_rep = []
    for r in reps:
        sys_ = System(name, {**base, **r}, pop)
        per_rep.append(measure(sys_))
    keys = [k for k in per_rep[0] if not k.startswith(("thr_", "tp_", "fp_")) and per_rep[0][k] is not None]
    dist = {}
    for k in keys:
        v = [m[k] for m in per_rep if m[k] is not None]
        dist[k] = {"mean": sum(v) / len(v), "std": _pstdev(v), "min": min(v), "max": max(v)}
    q_of = {d: pop.index[d][0] for d in subset}
    spread = {d: max(r[d] for r in reps) - min(r[d] for r in reps) for d in subset}
    flips_05 = sum(1 for d in subset if min(r[d] for r in reps) < 0.5 <= max(r[d] for r in reps))
    flips_tr = sum(1 for d in subset if thresholds.get(q_of[d]) is not None
                   and min(r[d] for r in reps) < thresholds[q_of[d]] <= max(r[d] for r in reps))
    sp = sorted(spread.values())
    return {
        "n_reps": len(reps), "n_rulings": len(subset),
        "metric_distribution": dist,
        "ruling_spread": {"max": sp[-1], "median": sp[len(sp) // 2], "p95": sp[min(len(sp) - 1, int(0.95 * len(sp)))],
                          "n_gt_0.05": sum(x > 0.05 for x in sp), "n_gt_0.1": sum(x > 0.1 for x in sp),
                          "n_identical": sum(x == 0 for x in sp)},
        "flips": {"at_0.5": flips_05, "at_transferred_threshold": flips_tr},
    }


def _pstdev(v: list[float]) -> float:
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

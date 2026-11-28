"""Tests of experiments/finetune/metrics.py.

Synthetic tests always run. The reproduction tests need the git-ignored data in data/derived/finetune/ and are
skipped without it: they assert that the module gives back the audit's numbers (docs/FINETUNE.md §4).
No mock: everything runs on in-memory data or on the stored per-ruling scores.
Run: uv run --frozen pytest experiments/finetune/tests -q
`FT_METRICS_PATH` points the tests at another copy of the module (used to show them red on a mutant).
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_path = os.environ.get("FT_METRICS_PATH") or str(ROOT / "experiments" / "finetune" / "metrics.py")
_spec = importlib.util.spec_from_file_location("ft_metrics", _path)
M = importlib.util.module_from_spec(_spec)
sys.modules["ft_metrics"] = M  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(M)

DATA = ROOT / "data" / "derived" / "finetune"
Q1, Q4 = M.QUARTERS


def _pop(spec: dict[str, list[tuple[str, bool, str, bool]]]) -> M.Population:
    """spec: quarter -> [(id, y, kind, couche1)]."""
    return M.Population({
        q: [M.Ruling(i, i.upper(), q, y, k, "de", "UV" if y else "autre", c1) for i, y, k, c1 in rows]
        for q, rows in spec.items()
    })


def test_auc_counts_ties_as_half():
    pop = _pop({Q1: [("a", True, "positive", True), ("b", True, "positive", True),
                     ("c", False, "hard_negative", True), ("d", False, "hard_negative", True)],
                Q4: [("e", True, "positive", True), ("f", False, "hard_negative", True)]})
    s = M.System("x", {"a": 3, "b": 2, "c": 1, "d": 2, "e": 5, "f": 0}, pop)
    m = M.measure(s)
    assert m[f"auc_hard_{Q1}"] == pytest.approx(3.5 / 4)
    # pooled: positives {3,2,5} vs hard {1,2,0}: 9 pairs, one tie (2,2)
    assert m["auc_hard_pooled"] == pytest.approx(8.5 / 9)


def test_weighted_auc_and_threshold_match_brute_force():
    rng = random.Random(3)
    rows = [(f"r{i}", i < 8, "positive" if i < 8 else "hard_negative", True) for i in range(40)]
    pop = _pop({Q1: rows, Q4: [("q4p", True, "positive", True), ("z", False, "easy_negative", True)]})
    scores = {r[0]: rng.choice([0.1, 0.2, 0.3, 0.5, 0.9]) for r in rows} | {"q4p": 1.0, "z": 0.0}
    s = M.System("x", scores, pop)
    w = {Q1: [rng.randint(0, 3) for _ in rows], Q4: [1, 1]}
    srt = s.by_q[Q1]
    rq = pop.rows[Q1]
    got = M.auc_weighted(srt, lambda i: rq[i].y, lambda i: w[Q1][i])
    num = den = 0.0
    for i, j in itertools.product(range(len(rq)), repeat=2):
        if rq[i].y and not rq[j].y:
            pw = w[Q1][i] * w[Q1][j]
            si, sj = scores[rq[i].decision_id], scores[rq[j].decision_id]
            num += pw * ((si > sj) + 0.5 * (si == sj))
            den += pw
    assert got == pytest.approx(num / den)
    t, f = M.best_threshold(s, Q1, w, layer1=False)
    npos = sum(w[Q1][i] for i, r in enumerate(rq) if r.y)
    cands = sorted({scores[r.decision_id] for i, r in enumerate(rq) if w[Q1][i] > 0})
    brute = [(M.f2_score(sum(w[Q1][i] for i, r in enumerate(rq) if r.y and scores[r.decision_id] >= c),
                         sum(w[Q1][i] for i, r in enumerate(rq) if not r.y and scores[r.decision_id] >= c), npos), c)
             for c in cands]
    best_f = max(b[0] for b in brute)
    assert f == pytest.approx(best_f)
    assert t == min(c for fb, c in brute if fb == best_f)  # ties: the lowest threshold


def test_best_threshold_tie_takes_lowest():
    # npos 2. At 0.9: TP1 FP0 -> F2 5/9. At 0.3: TP2 FP8 -> F2 5/9 as well (exact tie in floating point).
    # Between them only false positives are added (lower F2). The lowest tied threshold (0.3) must win.
    negs = [(f"n{i}", False, "hard_negative", True) for i in range(8)]
    pop = _pop({Q1: [("p", True, "positive", True), *negs, ("p2", True, "positive", True)],
                Q4: [("x", True, "positive", True), ("y", False, "easy_negative", True)]})
    sc = {"p": 0.9, "p2": 0.3, "x": 0.5, "y": 0.2} | {f"n{i}": 0.5 + i / 100 for i in range(8)}
    s = M.System("x", sc, pop)
    t, f = M.best_threshold(s, Q1, M.unit_weights(pop), layer1=False)
    assert f == M.f2_score(1, 0, 2) == M.f2_score(2, 8, 2)
    assert t == 0.3
    pop2 = _pop({Q1: [("p", True, "positive", True), ("p2", True, "positive", True),
                      ("n", False, "hard_negative", False)],
                 Q4: [("x", True, "positive", True), ("y", False, "easy_negative", True)]})
    # layer1: n is dropped by layer 1, so thresholds 0.5 and 0.2 give the same F2 on Q1; the lowest counted
    # candidate (0.5: the score of p2) wins, never the score of a row layer 1 dropped (0.2)
    s2 = M.System("x", {"p": 0.9, "p2": 0.5, "n": 0.2, "x": 0.5, "y": 0.2}, pop2)
    t2, f2 = M.best_threshold(s2, Q1, M.unit_weights(pop2), layer1=True)
    assert (t2, f2) == (0.5, 1.0)
    t3, _ = M.best_threshold(s2, Q1, M.unit_weights(pop2), layer1=False)
    assert t3 == 0.5  # without layer 1, n at 0.2 costs a false positive


def test_transferred_threshold_comes_from_the_other_quarter():
    pop = _pop({Q1: [("a", True, "positive", True), ("b", False, "hard_negative", True),
                     ("c", False, "easy_negative", True)],
                Q4: [("d", True, "positive", True), ("e", False, "hard_negative", True),
                     ("f", False, "easy_negative", True)]})
    # Q4's best threshold is 0.7 (d alone); applied to Q1 it misses a (0.6): F2 0 on Q1.
    s = M.System("x", {"a": 0.6, "b": 0.5, "c": 0.1, "d": 0.7, "e": 0.65, "f": 0.0}, pop)
    m = M.measure(s)
    assert m[f"thr_tr_full_{Q1}"] == 0.7 and m[f"f2_tr_full_{Q1}"] == 0.0
    assert m[f"thr_tr_full_{Q4}"] == 0.6 and m[f"tp_tr_full_{Q4}"] == 1 and m[f"fp_tr_full_{Q4}"] == 1


def test_layer1_drops_count_as_misses():
    pop = _pop({Q1: [("a", True, "positive", False), ("b", True, "positive", True),
                     ("c", False, "easy_negative", True)],
                Q4: [("d", True, "positive", True), ("e", False, "easy_negative", True)]})
    s = M.System("x", {"a": 0.9, "b": 0.8, "c": 0.1, "d": 0.8, "e": 0.1}, pop)
    m = M.measure(s)
    assert m[f"tp_tr_full_{Q1}"] == 2
    assert m[f"tp_tr_l1_{Q1}"] == 1  # a is dropped by layer 1, still counted in npos
    assert m["recall_tr_l1_pooled"] == pytest.approx(2 / 3)


def test_top_k_tie_at_cut_counts_expected_share():
    rows = [("p1", True, "positive", True), ("p2", True, "positive", True)] + [
        (f"n{i}", False, "easy_negative", True) for i in range(70)]
    pop = _pop({Q1: rows, Q4: [("q4p", True, "positive", True), ("q4n", False, "easy_negative", True)]})
    sc = {"p1": 1.0, "p2": 0.5, "q4p": 1.0, "q4n": 0.0} | {f"n{i}": (0.5 if i < 3 else 0.0) for i in range(70)}
    s = M.System("x", sc, pop)
    fl = M.top_k(s, Q1, M.unit_weights(pop), 2)
    # p1 is in; the second slot is shared by 4 tied rulings (p2 + 3 negatives): p2 counts 1/4
    assert fl.tp == pytest.approx(1.25)
    assert fl.found[1] == pytest.approx(0.25)


def test_missing_or_null_score_fails(tmp_path):
    pop = _pop({Q1: [("a", True, "positive", True)], Q4: [("b", False, "easy_negative", True)]})
    with pytest.raises(M.MetricsError):
        M.System("x", {"a": 0.5}, pop)
    p = tmp_path / "s.jsonl"
    p.write_text('{"decision_id": "a", "score": null}\n')
    with pytest.raises(M.MetricsError):
        M.load_scores_jsonl(p)


def test_paired_bootstrap_is_paired_and_reproducible():
    rows = [(f"p{i}", True, "positive", True) for i in range(5)] + [
        (f"n{i}", False, "hard_negative", True) for i in range(10)]
    rows4 = [(f"q4{r[0]}", *r[1:]) for r in rows]
    pop = _pop({Q1: rows, Q4: rows4})
    rng = random.Random(1)
    sa = {r[0]: rng.random() for r in rows + rows4}
    a, b = M.System("a", sa, pop), M.System("b", dict(sa), pop)
    boots = M.paired_bootstrap([a, b], n_boot=50, seed=5)
    assert all(bt["a"]["auc_hard_pooled"] == bt["b"]["auc_hard_pooled"] for bt in boots)  # same resamples
    again = M.paired_bootstrap([a, b], n_boot=50, seed=5)
    assert [bt["a"]["auc_hard_pooled"] for bt in boots] == [bt["a"]["auc_hard_pooled"] for bt in again]
    s = M.summarise([a, b], boots, ["auc_hard_pooled"], [("a", "b")])
    assert s["pairs"]["a - b"]["auc_hard_pooled"]["ci95"] == (0.0, 0.0)


# -- reproduction of the audit (needs the git-ignored data) ------------------------------------------------------
_HAVE = (DATA / "suva-ft-v3" / "fold_A" / "test.jsonl").is_file() and (DATA / "runs_v3").is_dir()
needs_data = pytest.mark.skipif(not _HAVE, reason="data/derived/finetune/ absent (git-ignored, D-031)")


@pytest.fixture(scope="module")
def audit():
    pop = M.load_population(DATA / "suva-ft-v3")

    def runs(m):
        s = {}
        for f in ("A", "B"):
            s.update(M.load_scores_jsonl(DATA / "runs_v3" / f"fold{f}_keera_{m}" / "test_scores.jsonl"))
        return s

    rule = M.load_rule_scores(DATA / "audit_v3" / "resultats" / "a02_features.json.gz")
    return pop, {"rule": rule, "8b": runs("8b"), "70b": runs("70b")}


# docs/FINETUNE.md §4 and the audit outputs (a04, a06, a07, a08)
EXPECTED = {
    "rule": {"auc_hard_2026Q1": 0.837, "auc_hard_2025Q4": 0.890, "f2_tr_full_2026Q1": 0.604,
             "f2_tr_full_2025Q4": 0.634, "f2_top45_2026Q1": 0.680, "f2_top45_2025Q4": 0.732,
             "f2_top60_2026Q1": 0.625, "f2_top60_2025Q4": 0.698, "auc_full_2026Q1": 0.989, "auc_full_2025Q4": 0.994},
    "8b": {"auc_hard_2026Q1": 0.789, "auc_hard_2025Q4": 0.853, "auc_hard_pooled": 0.817, "f2_tr_full_2026Q1": 0.685,
           "f2_tr_full_2025Q4": 0.688, "f2_tr_full_pooled": 0.686, "f2_top45_2026Q1": 0.680,
           "f2_top45_2025Q4": 0.669, "f2_top60_2026Q1": 0.652, "f2_top60_2025Q4": 0.610},
    "70b": {"auc_hard_2026Q1": 0.784, "auc_hard_2025Q4": 0.874, "auc_hard_pooled": 0.821, "f2_tr_full_2026Q1": 0.522,
            "f2_tr_full_2025Q4": 0.613, "f2_tr_full_pooled": 0.563, "f2_tr_l1_2026Q1": 0.561,
            "f2_tr_l1_2025Q4": 0.614, "f2_top45_2026Q1": 0.473, "f2_top45_2025Q4": 0.573,
            "f2_top60_2026Q1": 0.516, "f2_top60_2025Q4": 0.610},
}


@needs_data
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_reproduces_audit_numbers(audit, name):
    pop, scores = audit
    m = M.measure(M.System(name, scores[name], pop))
    got = {k: round(m[k], 3) for k in EXPECTED[name]}
    assert got == EXPECTED[name]


@needs_data
def test_reproduces_audit_counts_and_sensitivity(audit):
    pop, scores = audit
    m8, m70 = (M.measure(M.System(n, scores[n], pop)) for n in ("8b", "70b"))
    assert (m8["tp_tr_full_pooled"], m8["fp_tr_full_pooled"]) == (42, 28)
    assert (m70["tp_tr_full_pooled"], m70["fp_tr_full_pooled"]) == (41, 87)
    amb = M.load_ambiguous(DATA / "audit_v3" / "negatifs_ambigus_v3.csv")
    assert len(amb) == 25
    pop2 = pop.without(amb)
    r8, r70 = (M.measure(M.System(n, scores[n], pop2)) for n in ("8b", "70b"))
    assert (round(r8["auc_hard_pooled"], 3), round(r70["auc_hard_pooled"], 3)) == (0.877, 0.868)
    assert (round(r8["f2_tr_full_pooled"], 3), round(r70["f2_tr_full_pooled"], 3)) == (0.742, 0.594)


def test_rank_average_percentiles_and_ties():
    pop = _pop({Q1: [("a", True, "positive", True), ("b", False, "hard_negative", True),
                     ("c", False, "easy_negative", True), ("d", False, "easy_negative", True)],
                Q4: [("e", True, "positive", True), ("f", False, "easy_negative", True)]})
    s1 = {"a": 0.9, "b": 0.5, "c": 0.5, "d": 0.1, "e": 3.0, "f": 1.0}
    s2 = {"a": 1.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 0.0, "f": 9.0}
    got = M.rank_average(pop, [s1, s2])
    # Q1 n=4. s1 ranks: d 1, b/c tie (2+3)/2 = 2.5, a 4 -> /4. s2 ranks: a 1, d 2, c 3, b 4 -> /4.
    assert got["a"] == pytest.approx((4 / 4 + 1 / 4) / 2)
    assert got["b"] == pytest.approx((2.5 / 4 + 4 / 4) / 2)
    assert got["c"] == pytest.approx((2.5 / 4 + 3 / 4) / 2)
    assert got["d"] == pytest.approx((1 / 4 + 2 / 4) / 2)
    # Q4 ranked on its own (n=2), not pooled with Q1
    assert got["e"] == pytest.approx((2 / 2 + 1 / 2) / 2) and got["f"] == pytest.approx((1 / 2 + 2 / 2) / 2)
    with pytest.raises(M.MetricsError):
        M.rank_average(pop, [{"a": 1.0}])


@needs_data
def test_rank_average_of_one_system_keeps_its_per_quarter_ranking(audit):
    pop, scores = audit
    one = M.rank_average(pop, [scores["8b"]])
    m0, m1 = M.measure(M.System("8b", scores["8b"], pop)), M.measure(M.System("8b%", one, pop))
    for k in ("auc_hard_2026Q1", "auc_hard_2025Q4", "f2_top45_pooled", "f2_top60_pooled", "auc_full_2026Q1"):
        assert m1[k] == pytest.approx(m0[k])

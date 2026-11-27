# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the benchmark: cases, scoring, statistics, the runner and replay (no network)."""
import dataclasses
import json

import pytest

from eval.tool_bench import score as sc
from eval.tool_bench.cases import PROFILES, build_cases, load_rulings, split_considerations
from eval.tool_bench.run import CONFIGS, cache_salt, export_golden, main, run_bench

from .fakes import make_gateway, synthetic_rulings


@pytest.fixture(scope="module")
def rulings_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("bench") / "rulings.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in synthetic_rulings()), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def cases(rulings_file):
    cs, warnings = build_cases(load_rulings(rulings_file), "quick", seed=5)
    assert warnings == []
    return cs


# ---------------------------------------------------------------- cases

def test_loader_drops_every_field_outside_the_allow_list(rulings_file):
    recs = load_rulings(rulings_file)
    assert recs and all(set(r) == {"docket", "language", "considerations"} for r in recs)
    assert "MUST_NOT_LEAK" not in json.dumps(recs)


def test_cases_are_deterministic_and_cover_every_category_and_language(rulings_file):
    a, _ = build_cases(load_rulings(rulings_file), "quick", seed=5)
    b, _ = build_cases(load_rulings(rulings_file), "quick", seed=5)
    assert a == b
    assert {c["category"] for c in a} == {"simple", "parallel", "parallel_multiple", "irrelevance", "evidence"}
    assert {c["lang"] for c in a} == {"de", "fr", "it"}
    assert a != build_cases(load_rulings(rulings_file), "quick", seed=6)[0]


def test_evidence_gold_is_unique_and_absent_passages_are_absent(cases):
    for c in (c for c in cases if c["category"] == "evidence"):
        passage = c["q"].split("«")[1].split("»")[0].strip()
        holders = [line.split("]")[0][1:] for line in c["data"].split("\n") if passage in line]
        assert holders == ([] if c["gold"]["a_consideration"] == "none" else [c["gold"]["a_consideration"]])


def test_full_profile_sizes():
    cs, _ = build_cases(synthetic_rulings(per_lang=4), "full", seed=5)
    ev = [c for c in cs if c["category"] == "evidence"]
    assert len(ev) == 3 * (PROFILES["full"]["evidence_present"] + PROFILES["full"]["evidence_absent"])


def test_fallback_splitter():
    text = ("Sachverhalt: ... Erwägungen:\n1. Die Beschwerde ist zulässig.\n2.1 Strittig ist X.\n2.2 Y.\n"
            "Demnach erkennt das Bundesgericht: 1.")
    assert [c["e_number"] for c in split_considerations(text)] == ["1", "2.1", "2.2"]
    assert split_considerations("no structure") == []


# ---------------------------------------------------------------- scoring and statistics

def test_ast_scoring_is_a_multiset_and_never_maps_one_id_onto_another():
    gold = [["get_consideration", {"a_id": "c2"}], ["get_consideration", {"a_id": "c2"}]]
    assert sc.score_calls(gold, list(reversed(gold)))["exact"]
    assert not sc.score_calls(gold, gold[:1])["exact"]
    assert not sc.score_calls([["get_consideration", {"a_id": "c7"}]],
                              [["get_consideration", {"a_id": "E. 4.2"}]])["exact"]
    assert sc.score_calls([["lookup_ruling", {"a_docket": "8C_1/2025"}]],
                          [["lookup_ruling", {"a_docket": "8c 1/2025"}]])["exact"]
    assert sc.score_calls([["find_article", {"a_act": "UVG", "b_number": "6"}]],
                          [["find_article", {"a_act": "UVG", "b_number": "Art. 6"}]])["exact"]
    assert sc.score_calls([], [])["exact"] and sc.score_calls([], [])["precision"] == 1.0


@pytest.mark.parametrize("k, n, lo, hi", [(0, 0, 0.0, 1.0), (10, 10, 0.722, 1.0), (17, 20, 0.640, 0.948),
                                          (0, 10, 0.0, 0.278)])
def test_wilson_interval(k, n, lo, hi):
    a, b = sc.wilson(k, n)
    assert a == pytest.approx(lo, abs=1e-3) and b == pytest.approx(hi, abs=1e-3)


def test_paired_bootstrap_detects_a_real_difference_and_not_noise():
    a = {(i, 0): 1.0 for i in range(40)}
    b = {(i, 0): (0.0 if i < 20 else 1.0) for i in range(40)}
    diff, lo, hi, n = sc.paired_bootstrap(a, b)
    assert n == 40 and diff == -0.5 and hi < 0
    d2, lo2, hi2, _ = sc.paired_bootstrap(a, a)
    assert d2 == lo2 == hi2 == 0.0


# ---------------------------------------------------------------- runner

def test_oracle_scores_one_everywhere(cases):
    rows, replies = run_bench(cases, make_gateway(cases, "oracle"), models=["apertus-v1-5-70b"], configs=CONFIGS)
    assert rows and all(r["exact"] and r["exact_raw"] and r["valid"] for r in rows), \
        [(r["config"], r["case_id"]) for r in rows if not r["exact"]][:5]
    assert all(r["accepted_invalid_ids"] == 0 for r in rows)
    assert {r["config"] for r in rows if r["category"] != "evidence"} == {"json_strict", "json_object", "native_auto"}


def test_noisy_replies_are_wrong_raw_and_right_after_validation(cases):
    rows, _ = run_bench(cases, make_gateway(cases, "noisy"), models=["m70b"], configs=["json_object", "native_auto"])
    with_ids = [r for r in rows if r["noncanonical_ids"]]
    assert with_ids and all(not r["exact_raw"] and r["exact"] for r in with_ids)
    assert all(r["invented_ids"] == 0 and r["accepted_invalid_ids"] == 0 for r in rows)


def test_garbage_fails_closed_and_never_crashes(cases):
    rows, _ = run_bench(cases, make_gateway(cases, "garbage"), models=["m"], configs=CONFIGS)
    gold_calls = [r for r in rows if r["category"] != "irrelevance"]
    assert all(not r["exact"] and r["calls"] == [] for r in gold_calls)
    assert all(r["accepted_invalid_ids"] == 0 for r in rows)


def test_report_thresholds_and_comparisons_on_rows(cases):
    rows, _ = run_bench(cases, make_gateway(cases, "oracle"), models=["apertus-v1-5-70b"], configs=CONFIGS)
    rep = sc.report(rows)
    assert rep["apertus-v1-5-70b / json_strict"]["overall"]["exact"] == 1.0
    checks = sc.check_thresholds(rows)
    assert all(c["pass"] for c in checks if c["id"] in ("T1", "T3", "T4", "T5"))
    cmp_ = sc.compare_configs(rows, "json_strict", "native_forced", category="evidence")
    assert cmp_["apertus-v1-5-70b"]["diff"] == 0.0


def test_non_regression_flags_a_drop(cases):
    good, _ = run_bench(cases, make_gateway(cases, "oracle"), models=["m"], configs=["json_strict"])
    bad, _ = run_bench(cases, make_gateway(cases, "garbage"), models=["m"], configs=["json_strict"])
    res = sc.compare_runs(good, bad)
    assert res["regressions"] and not sc.compare_runs(good, good)["regressions"]


def test_cli_live_then_replay_gives_identical_rows(rulings_file, tmp_path, monkeypatch, cases):
    import tests.tool_bench.fakes as fakes
    monkeypatch.setattr(fakes, "bench_factory", make_gateway(cases, "oracle"), raising=False)
    live = tmp_path / "live"
    code = main(["--rulings", str(rulings_file), "--models", "apertus-v1-5-70b", "--all", "--chat",
                 "tests.tool_bench.fakes:bench_factory", "--out", str(live),
                 "--export-golden", str(tmp_path / "g.jsonl")])
    assert (live / "report.md").exists() and (live / "report.json").exists()
    replay = tmp_path / "replay"
    code2 = main(["--rulings", str(rulings_file), "--models", "apertus-v1-5-70b", "--replay",
                  str(live / "replies.jsonl"), "--out", str(replay)])
    strip = lambda p: [{k: v for k, v in json.loads(x).items() if k not in ("latency_s", "replay_request_changed")}  # noqa: E731
                       for x in p.read_text(encoding="utf-8").splitlines()]
    assert strip(live / "rows.jsonl") == strip(replay / "rows.jsonl")
    meta = json.loads((replay / "report.json").read_text())["meta"]
    assert meta["mode"] == "REPLAY" and meta["replay_requests_changed"] == 0 and meta["job_exceptions"] == 0
    live_meta = json.loads((live / "report.json").read_text())["meta"]
    assert live_meta["run_id"].startswith("live@") and meta["run_id"] == live_meta["run_id"]
    assert live_meta["cache_hits"] == 0
    assert not (live / "partial.jsonl").exists()  # removed once the run is complete
    assert code == code2
    golden = [json.loads(x) for x in (tmp_path / "g.jsonl").read_text(encoding="utf-8").splitlines()]
    assert golden and all(g["expected"]["valid"] for g in golden)


def test_export_golden_only_takes_json_evidence(cases, tmp_path):
    rows, replies = run_bench(cases, make_gateway(cases, "oracle"), models=["m"], configs=CONFIGS)
    n = export_golden(rows, replies, cases, tmp_path / "g.jsonl")
    assert n == sum(1 for r in rows if r["category"] == "evidence" and r["config"].startswith("json"))


# ---------------------------------------------------------------- review fixes: scoring, statistics, runner

def test_irrelevance_counts_any_emitted_call_even_a_refused_one(cases):
    rows, _ = run_bench(cases, make_gateway(cases, "overeager"), models=["m"], configs=["json_object", "native_auto"])
    irr = [r for r in rows if r["category"] == "irrelevance"]
    assert irr and all(not r["exact"] and not r["exact_raw"] and r["raw_calls"] for r in irr)
    ok, _ = run_bench(cases, make_gateway(cases, "oracle"), models=["m"], configs=["json_object", "native_auto"])
    assert all(r["exact"] for r in ok if r["category"] == "irrelevance")


def test_plain_text_answers_are_recorded_not_credited(cases):
    rows, _ = run_bench(cases, make_gateway(cases, "text"), models=["m"], configs=["native_auto"])
    ev = [r for r in rows if r["category"] == "evidence"]
    assert ev and all(r["text_exact"] is True and not r["exact"] for r in ev)
    m = sc.metrics(ev)
    assert m["answered_in_text"] == m["text_answer_correct"] == len(ev)


def test_repetitions_and_runs_get_distinct_cache_salts(cases):
    salts: dict[str, set] = {}
    oracle = make_gateway(cases, "oracle")("m")

    def chat_for(run_id):
        def chat(req):
            salts.setdefault(run_id, set()).add(req.cache_salt)
            return oracle(req)
        return chat

    for run_id in ("quick@t1", "quick@t2"):
        run_bench(cases[:3], lambda m, r=run_id: chat_for(r), models=["m"], configs=["json_strict", "native_auto"],
                  reps=2, run_id=run_id)
    assert salts["quick@t1"] == {"quick@t1/rep0", "quick@t1/rep1"}
    assert not salts["quick@t1"] & salts["quick@t2"]      # a second run is never served from the first (G10)
    assert cache_salt("", 0) == "" and cache_salt("", 1) == "rep1"   # legacy form, replay of old runs only


def _cli(rulings_file, out, *extra):
    return ["--rulings", str(rulings_file), "--models", "apertus-v1-5-70b", "--chat",
            "tests.tool_bench.fakes:bench_factory", "--out", str(out), *extra]


def test_a_live_run_needs_limit_or_all_and_dry_run_calls_nothing(rulings_file, tmp_path, monkeypatch, capsys):
    import tests.tool_bench.fakes as fakes
    calls = []
    monkeypatch.setattr(fakes, "bench_factory", lambda m: calls.append(m), raising=False)
    with pytest.raises(SystemExit) as e:
        main(_cli(rulings_file, tmp_path / "a"))
    assert e.value.code == 2 and not calls and not (tmp_path / "a").exists()
    assert main(_cli(rulings_file, tmp_path / "b", "--all", "--dry-run")) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["dry_run"] and shown["jobs"] > 0 and not calls and not (tmp_path / "b").exists()


def test_limit_caps_the_cases(rulings_file, tmp_path, monkeypatch, cases):
    import tests.tool_bench.fakes as fakes
    monkeypatch.setattr(fakes, "bench_factory", make_gateway(cases, "oracle"), raising=False)
    main(_cli(rulings_file, tmp_path / "l", "--limit", "3"))
    meta = json.loads((tmp_path / "l" / "report.json").read_text())["meta"]
    assert meta["cases"] == 3 and meta["limit"] == 3


def test_a_live_run_served_from_the_cache_is_not_a_measurement(rulings_file, tmp_path, monkeypatch, cases):
    import tests.tool_bench.fakes as fakes
    oracle = make_gateway(cases, "oracle")

    def cached_factory(model):
        chat = oracle(model)
        return lambda req: dataclasses.replace(chat(req), mode="REPLAY")

    monkeypatch.setattr(fakes, "bench_factory", cached_factory, raising=False)
    assert main(_cli(rulings_file, tmp_path / "c", "--all")) == 3
    assert json.loads((tmp_path / "c" / "report.json").read_text())["meta"]["cache_hits"] > 0


def test_a_job_that_raises_becomes_a_row_and_the_run_goes_on(cases, tmp_path):
    oracle = make_gateway(cases, "oracle")("m")
    bad_q = cases[0]["q"]

    def chat(req):
        if req.messages[1]["content"].endswith(bad_q):
            raise ValueError("boom")
        return oracle(req)

    partial = tmp_path / "partial.jsonl"
    rows, _ = run_bench(cases, lambda m: chat, models=["m"], configs=["json_strict"], partial=partial)
    broken = [r for r in rows if r["request_error"] == "exception:ValueError"]
    assert len(broken) == 1 and not broken[0]["exact"] and sum(r["exact"] for r in rows) == len(rows) - 1
    assert len(partial.read_text(encoding="utf-8").splitlines()) == len(rows)


def test_cluster_bootstrap_does_not_narrow_when_a_run_is_duplicated():
    one = {(i, 0): float(i % 3 == 0) for i in range(30)}
    base = {(i, 0): 1.0 for i in range(30)}
    two = {**one, **{(i, 1): v for (i, _), v in one.items()}}
    base2 = {**base, **{(i, 1): v for (i, _), v in base.items()}}
    assert sc.paired_bootstrap(base, one)[:3] == pytest.approx(sc.paired_bootstrap(base2, two)[:3])


def _rows(model, config, lang, n, k, rep=0, category="evidence"):
    return [{"model": model, "config": config, "rep": rep, "case_id": f"{lang}-{i}", "category": category,
             "lang": lang, "exact": i < k, "exact_first": i < k, "exact_raw": i < k, "valid": True}
            for i in range(n)]


@pytest.mark.parametrize("native_k, n, verdict", [(20, 20, "native_candidate"), (12, 20, "keep_json"),
                                                  (10, 10, "insufficient_n")])
def test_decision_rule_is_computed_per_language(native_k, n, verdict):
    rows = []
    for lang in ("de", "fr", "it"):
        rows += _rows("apertus-v1-5-70b", "json_strict", lang, n, n // 2)
        rows += _rows("apertus-v1-5-70b", "native_forced", lang, n, native_k)
    assert sc.decide(rows)["verdict"] == verdict


def test_compare_runs_needs_the_same_cases_and_does_not_fire_on_one_flip():
    base = _rows("m", "json_strict", "de", 9, 9)
    flip = _rows("m", "json_strict", "de", 9, 8)
    res = sc.compare_runs(base, flip)
    assert res["regressions"] == [] and res["watch"] == ["m / json_strict / evidence"]
    other = _rows("m", "json_strict", "fr", 9, 9)
    assert sc.compare_runs(base, other)["not_comparable"]
    assert sc.main(["--compare", "/dev/null", "/dev/null"]) == 0


def test_thresholds_are_judged_on_the_worst_repetition():
    rows = _rows("apertus-v1-5-70b", "json_strict", "de", 20, 20, rep=0)
    rows += _rows("apertus-v1-5-70b", "json_strict", "de", 20, 10, rep=1)
    t4 = [c for c in sc.check_thresholds(rows) if c["id"] == "T4"][0]
    assert not t4["pass"] and t4["value"] == 0.5 and t4["value_by_rep"] == {0: 1.0, 1: 0.5}


def test_loader_numbers_considerations_without_ids(tmp_path):
    p = tmp_path / "r.jsonl"
    rec = {"docket": "8C_1/2025", "language": "de",
           "considerations": [{"number": "1", "text": "a"}, {"number": "2", "text": "b"}, {"text": "c"}]}
    p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    cons = load_rulings(p)[0]["considerations"]
    assert [(c["id"], c["e_number"]) for c in cons] == [("c1", "1"), ("c2", "2"), ("c3", "")]


def test_case_ids_are_content_derived_and_unique(cases):
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == len(ids) and all(len(i.rsplit("-", 1)[1]) == 10 for i in ids)

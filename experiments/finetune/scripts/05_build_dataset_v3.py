"""Build suva-ft-v3: temporal cross-validation on COMPLETE quarters + T3/2025 summaries as extra positives.

fold_A: train/valid = T4/2025 complete (+ 23 T3/2025 summaries as positives, train only), test = T1/2026 complete
fold_B: train/valid = T1/2026 complete (+ same 23 T3 positives, train only),            test = T4/2025 complete
valid = 20 % of the training quarter, stratified by kind. T3/2025 NEGATIVES are NOT used: the T3 list is
incomplete (summaries only), so the rest of T3 would contain unlabelled positives.
Each record carries meta.couche1 (layer-1 whitelist E, see filtre_couche1/) : a hint, never a label.
Selection/order = sort by sha256(seed:decision_id) -> deterministic, independent of read order.
Usage: python3 -I 05_build_dataset_v3.py --parquet bger.parquet --population population_tf_hf_2025Q3_2026Q2.csv --out ../data_v3
"""
import argparse, csv, hashlib, importlib.util, json, os, sys
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("v2", os.path.join(HERE, "04_build_dataset_v2.py"))
v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)
SYSTEM_TRIAGE, QUESTION, prep_text = v2.SYSTEM_TRIAGE, v2.QUESTION, v2.prep_text
POS = {"2025Q4": "positif 2025 Q4", "2026Q1": "positif 2026 Q1"}



def key(seed, did):
    return hashlib.sha256(f"{seed}:{did}".encode()).hexdigest()


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True); ap.add_argument("--population", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--cap", type=int, default=14000)
    ap.add_argument("--seed", type=int, default=42); ap.add_argument("--valid-frac", type=float, default=0.2)
    a = ap.parse_args()
    fpath = os.path.join(HERE, "..", "filtre_couche1", "filtre_e.py")
    fs = importlib.util.spec_from_file_location("fe", fpath); fe = importlib.util.module_from_spec(fs); fs.loader.exec_module(fe)
    allrows = list(csv.DictReader(open(a.population, encoding="utf-8")))
    q = {k: [] for k in ("2025Q3", "2025Q4", "2026Q1")}
    for r in allrows:
        t = r["trimestre_decision"]
        if t in POS:
            r["kind"] = "positive" if r["label_suva"] == POS[t] else ("hard_negative" if r["matiere"] in ("UV", "IV", "MV") else "easy_negative")
            r["label_source"] = "liste Suva" if r["kind"] == "positive" else "reste du trimestre"
            q[t].append(r)
        elif t == "2025Q3" and r["label_suva"].startswith("resume"):
            r["kind"] = "positive"; r["label_source"] = "résumé Suva T3/2025 (hors liste)"
            q[t].append(r)
    assert len(q["2025Q3"]) == 23, len(q["2025Q3"])
    ids = [r["decision_id"] for v in q.values() for r in v]
    assert len(ids) == len(set(ids))
    con = duckdb.connect(); con.execute("create temp table want(decision_id varchar)")
    con.executemany("insert into want values (?)", [(i,) for i in ids])
    texts = dict(con.execute(f"select b.decision_id, b.full_text from read_parquet('{a.parquet}') b join want using (decision_id)").fetchall())
    missing = [i for i in ids if not texts.get(i)]
    assert not missing, missing

    def split_quarter(rows):
        tr, va = [], []
        for k in ("positive", "hard_negative", "easy_negative"):
            items = sorted((r for r in rows if r["kind"] == k), key=lambda r: key(a.seed, r["decision_id"]))
            n = round(len(items) * a.valid_frac); va += items[:n]; tr += items[n:]
        return tr, va

    folds = {}
    for name, trq, teq in (("fold_A", "2025Q4", "2026Q1"), ("fold_B", "2026Q1", "2025Q4")):
        tr, va = split_quarter(q[trq])
        folds[name] = {"train": tr + q["2025Q3"], "valid": va, "test": list(q[teq])}
    stats = {"seed": a.seed, "cap": a.cap, "folds": {}}
    for fname, splits in folds.items():
        d = os.path.join(a.out, fname); os.makedirs(d, exist_ok=True); stats["folds"][fname] = {}
        for sname, rows in splits.items():
            rows.sort(key=lambda r: key(a.seed, r["decision_id"]))
            with open(os.path.join(d, f"{sname}.jsonl"), "w", encoding="utf-8") as f:
                for r in rows:
                    full = texts[r["decision_id"]]; text = prep_text(full, a.cap)
                    f.write(json.dumps({
                        "prompt": [{"role": "system", "content": SYSTEM_TRIAGE},
                                   {"role": "user", "content": f"Urteil {r['docket']}:\n\n{text}\n\n{QUESTION}"}],
                        "completion": [{"role": "assistant", "content": "Ja" if r["kind"] == "positive" else "Nein"}],
                        "meta": {"decision_id": r["decision_id"], "docket": r["docket"], "lang": r["lang"],
                                 "decision_date": r["decision_date"], "quarter": r["trimestre_decision"],
                                 "prefixe": r["prefixe"], "matiere": r["matiere"], "legal_area": r["legal_area"],
                                 "kind": r["kind"], "label_source": r["label_source"], "couche1": fe.passe(r),
                                 "chars_full": len(full), "chars_sent": len(text)},
                    }, ensure_ascii=False) + "\n")
            c = {"n": len(rows)}
            for r in rows: c[r["kind"]] = c.get(r["kind"], 0) + 1
            c["couche1"] = sum(fe.passe(r) for r in rows)
            stats["folds"][fname][sname] = c
    json.dump(stats, open(os.path.join(a.out, "stats.json"), "w"), indent=2)
    print(json.dumps(stats["folds"], indent=2))


if __name__ == "__main__":
    main()

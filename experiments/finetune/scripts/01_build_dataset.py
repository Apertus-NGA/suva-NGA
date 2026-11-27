"""Build the Suva relevance fine-tuning dataset (experimental, NOT for the hack repo).

Train = rulings decided in Q4/2025, test = Q1/2026 (temporal split, no leakage).
Labels = Suva positives list; negatives = the rest of the TF population (closed world).
Prompt = exactly the V1 prompt of the Keera tests (tests-keera/scripts/quality.py) so the
fine-tuned 8B is directly comparable with the zero-shot 8B/70B logprob baseline.

Usage: python3 01_build_dataset.py --parquet bger.parquet --population population_tf_hf_2025Q3_2026Q2.csv --out ../data
"""
import argparse, json, random, os
import duckdb

SYSTEM_TRIAGE = (
    "Du bist juristische Assistenz der Suva (Schweizerische Unfallversicherungsanstalt). Die Suva verfolgt die "
    "Rechtsprechung des Bundesgerichts und wählt die Urteile aus, die für ihre Praxis als Unfallversicherer "
    "relevant sind. Typisch relevant: Unfallversicherung (UVG) und Militärversicherung (MVG); die Suva oder ein "
    "anderer UVG-Versicherer ist Partei; Fragen wie Unfallbegriff, Kausalzusammenhang, Invalidenrente, "
    "Integritätsentschädigung, Taggeld, Heilbehandlung, Prämien und Unterstellung, Regress; Urteile anderer "
    "Rechtsgebiete (z. B. IV, BVG, Haftpflicht, Zivilrecht), wenn sie die Praxis eines Unfallversicherers "
    "beeinflussen. Typisch nicht relevant: Urteile ohne Bezug zur Unfall- oder Militärversicherung."
)
QUESTION = "Ist dieses Urteil für die Suva relevant? Antworte nur mit Ja oder Nein."


def prep_text(text: str, cap: int, head: int = 12000) -> str:
    if len(text) <= cap:
        return text
    return text[:head] + "\n[…]\n" + text[-(cap - head):]


def sample(rows, quarter, n_social_random, n_other_random, rng):
    q = [r for r in rows if r["trimestre_decision"] == quarter]
    pos = [r for r in q if r["label_suva"]]
    neg = [r for r in q if not r["label_suva"]]
    hard = [r for r in neg if r["matiere"] in ("UV", "IV", "MV")]
    rest = [r for r in neg if r["matiere"] not in ("UV", "IV", "MV")]
    social = [r for r in rest if r["prefixe"] in ("8C", "9C")]
    other = [r for r in rest if r["prefixe"] not in ("8C", "9C")]
    rs = (rng.sample(social, min(n_social_random, len(social))) +
          rng.sample(other, min(n_other_random, len(other))))
    out = ([(r, "positive") for r in pos] + [(r, "hard_negative") for r in hard] +
           [(r, "random_negative") for r in rs])
    rng.shuffle(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--population", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=int, default=14000, help="max characters of ruling text (≈4k tokens)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--valid-frac", type=float, default=0.2)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    con = duckdb.connect()
    pop = con.execute(f"select * from read_csv_auto('{a.population}', all_varchar=true) "
                      "where trimestre_decision in ('2025Q4','2026Q1')").fetchdf().to_dict("records")
    for r in pop:
        r["label_suva"] = bool(r["label_suva"]) and str(r["label_suva"]) not in ("nan", "None", "")
    splits = {
        "train_all": sample(pop, "2025Q4", 80, 80, rng),
        "test": sample(pop, "2026Q1", 150, 150, rng),
    }
    ids = sorted({r["decision_id"] for s in splits.values() for r, _ in s})
    con.execute("create temp table want(decision_id varchar)")
    con.executemany("insert into want values (?)", [(i,) for i in ids])
    texts = dict(con.execute(f"select b.decision_id, b.full_text from read_parquet('{a.parquet}') b "
                             "join want using (decision_id)").fetchall())
    missing = [i for i in ids if not texts.get(i)]
    if missing:
        print(f"WARNING: {len(missing)} rulings without text, dropped: {missing[:5]}")
    # train/valid split stratified by label kind
    train, valid = [], []
    for kind in ("positive", "hard_negative", "random_negative"):
        items = [x for x in splits["train_all"] if x[1] == kind and texts.get(x[0]["decision_id"])]
        k = max(1, round(len(items) * a.valid_frac))
        valid += items[:k]
        train += items[k:]
    rng.shuffle(train); rng.shuffle(valid)
    final = {"train": train, "valid": valid,
             "test": [x for x in splits["test"] if texts.get(x[0]["decision_id"])]}
    os.makedirs(a.out, exist_ok=True)
    stats = {}
    for name, items in final.items():
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r, kind in items:
                text = prep_text(texts[r["decision_id"]], a.cap)
                user = f"Urteil {r['docket']}:\n\n{text}\n\n{QUESTION}"
                f.write(json.dumps({
                    "prompt": [{"role": "system", "content": SYSTEM_TRIAGE}, {"role": "user", "content": user}],
                    "completion": [{"role": "assistant", "content": "Ja" if kind == "positive" else "Nein"}],
                    "meta": {"decision_id": r["decision_id"], "docket": r["docket"], "lang": r["lang"],
                             "quarter": r["trimestre_decision"], "matiere": r["matiere"], "kind": kind,
                             "chars_full": len(texts[r["decision_id"]]), "chars_sent": len(text)},
                }, ensure_ascii=False) + "\n")
        stats[name] = {k: sum(1 for _, kk in items if kk == k)
                       for k in ("positive", "hard_negative", "random_negative")}
    json.dump({"seed": a.seed, "cap": a.cap, "counts": stats}, open(os.path.join(a.out, "stats.json"), "w"), indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()

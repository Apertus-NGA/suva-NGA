"""Build suva-ft-v2: COMPLETE Federal Court population per quarter (no sampling of negatives).

test  = every ruling decided in Q1/2026 (2,005; 31 Suva positives, 1,974 negatives)
train + valid = every ruling decided in Q4/2025 (1,931; 28 positives), valid = 20 % stratified by kind
Labels = Suva xlsx list (population-tf label_suva), quarters by DECISION date.
Selection and order depend only on sha256(seed:decision_id), never on file read order -> deterministic.
Prompt and 14k-char cap identical to suva-ft-v1 / Keera tests V1.

Usage: python3 -I 04_build_dataset_v2.py --parquet bger.parquet --population population_tf_hf_2025Q3_2026Q2.csv --out ../data_v2
"""
import argparse, csv, hashlib, json, os
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
POS = {"2025Q4": "positif 2025 Q4", "2026Q1": "positif 2026 Q1"}


def prep_text(text, cap, head=12000):
    return text if len(text) <= cap else text[:head] + "\n[…]\n" + text[-(cap - head):]


def key(seed, did):
    return hashlib.sha256(f"{seed}:{did}".encode()).hexdigest()


def kind(r):
    if r["label_suva"] == POS[r["trimestre_decision"]]:
        return "positive"
    return "hard_negative" if r["matiere"] in ("UV", "IV", "MV") else "easy_negative"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True); ap.add_argument("--population", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--cap", type=int, default=14000)
    ap.add_argument("--seed", type=int, default=42); ap.add_argument("--valid-frac", type=float, default=0.2)
    a = ap.parse_args()
    pop = [r for r in csv.DictReader(open(a.population, encoding="utf-8")) if r["trimestre_decision"] in POS]
    ids = [r["decision_id"] for r in pop]
    assert len(ids) == len(set(ids)), "duplicate decision_id in population"
    con = duckdb.connect()
    con.execute("create temp table want(decision_id varchar)")
    con.executemany("insert into want values (?)", [(i,) for i in ids])
    got = con.execute(f"select b.decision_id, b.full_text from read_parquet('{a.parquet}') b join want using (decision_id)").fetchall()
    texts = {}
    for did, t in got:
        assert did not in texts, f"duplicate text row {did}"
        texts[did] = t
    missing = [i for i in ids if not texts.get(i)]
    print(f"population rows {len(pop)}, texts found {len(texts)}, missing/empty {len(missing)} {missing[:10]}")
    splits = {"train": [], "valid": [], "test": []}
    for r in pop:
        r["kind"] = kind(r)
    for r in pop:
        if r["trimestre_decision"] == "2026Q1":
            splits["test"].append(r)
    for k in ("positive", "hard_negative", "easy_negative"):
        items = sorted((r for r in pop if r["trimestre_decision"] == "2025Q4" and r["kind"] == k),
                       key=lambda r: key(a.seed, r["decision_id"]))
        n = round(len(items) * a.valid_frac)
        splits["valid"] += items[:n]; splits["train"] += items[n:]
    os.makedirs(a.out, exist_ok=True)
    stats = {"seed": a.seed, "cap": a.cap, "missing_text": missing, "counts": {}}
    for name, rows in splits.items():
        rows.sort(key=lambda r: key(a.seed, r["decision_id"]))
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                full = texts.get(r["decision_id"]) or ""
                text = prep_text(full, a.cap)
                f.write(json.dumps({
                    "prompt": [{"role": "system", "content": SYSTEM_TRIAGE},
                               {"role": "user", "content": f"Urteil {r['docket']}:\n\n{text}\n\n{QUESTION}"}],
                    "completion": [{"role": "assistant", "content": "Ja" if r["kind"] == "positive" else "Nein"}],
                    "meta": {"decision_id": r["decision_id"], "docket": r["docket"], "lang": r["lang"],
                             "decision_date": r["decision_date"], "quarter": r["trimestre_decision"],
                             "prefixe": r["prefixe"], "matiere": r["matiere"], "kind": r["kind"],
                             "chars_full": len(full), "chars_sent": len(text), "no_text": not full},
                }, ensure_ascii=False) + "\n")
        c = {}
        for r in rows: c[r["kind"]] = c.get(r["kind"], 0) + 1
        stats["counts"][name] = {"n": len(rows), **c}
    json.dump(stats, open(os.path.join(a.out, "stats.json"), "w"), indent=2)
    print(json.dumps(stats["counts"], indent=2))


if __name__ == "__main__":
    main()

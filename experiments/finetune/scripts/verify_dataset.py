"""Vérifie qu'un jeu de données fine-tuning Suva est EXACTEMENT celui du manifeste figé.

Usage : python3 -I verify_dataset.py --manifest MANIFEST_suva_ft_v1.json --data ../data
Sortie 0 = identique (les deux personnes qui comparent ont le même jeu), 1 = divergence (détail affiché).
Ne dépend que de la bibliothèque standard.
"""
import argparse, hashlib, json, os, sys


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ids_digest(rows):
    # empreinte indépendante du texte : split, decision_id, label, triés
    lines = sorted(f"{r['split']}\t{r['decision_id']}\t{r['label']}" for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    m = json.load(open(a.manifest, encoding="utf-8"))
    ok = True
    seen = []
    for split, info in m["splits"].items():
        p = os.path.join(a.data, info["file"])
        if not os.path.exists(p):
            print(f"[KO] {split}: fichier absent {p}"); ok = False; continue
        got = sha256_file(p)
        if got != info["sha256"]:
            print(f"[KO] {split}: SHA-256 fichier {got[:16]}… ≠ attendu {info['sha256'][:16]}…"); ok = False
        recs = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        ids = [r["meta"]["decision_id"] for r in recs]
        if ids != info["decision_ids_in_order"]:
            print(f"[KO] {split}: liste ou ordre des decision_id différent"); ok = False
        for r in recs:
            seen.append({"split": split, "decision_id": r["meta"]["decision_id"],
                         "label": r["completion"][0]["content"]})
        print(f"[{'OK' if got == info['sha256'] else 'KO'}] {split}: {len(recs)} lignes")
    d = ids_digest(seen)
    if d != m["ids_digest_sha256"]:
        print(f"[KO] empreinte ids {d[:16]}… ≠ {m['ids_digest_sha256'][:16]}…"); ok = False
    print("IDENTIQUE au manifeste" if ok else "DIVERGENCE : ne pas comparer les résultats")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

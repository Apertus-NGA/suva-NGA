"""Shared data, features, gates and evaluation for the relevance experiments.

Build once:   uv run python research/common.py        (writes research/cache/dataset.pkl)
Use:          from common import load, evaluate, DET_FEATURES, ...

Conventions
- Labelled quarters: "2025 Q4" and "2026 Q1" (59 relevant). "2026 Q2" is the unlabelled target.
- `cand` = passes the deterministic gates (8C/9C, area UV/MV/IV, not single-judge).
- Every metric counts ALL relevant rulings of the test quarter; a relevant ruling
  outside the scored scope is a miss.
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUT = ROOT / "out"
DSN = "postgresql://suva@localhost:54329/suva"
LABELLED = ["2025 Q4", "2026 Q1"]

SUVA = r"\b(?:Suva|SUVA|CNA|INSAI)\b|Unfallversicherungsanstalt|Caisse nationale suisse|Istituto nazionale svizzero"
RE_FACTS = re.compile(r"\n\s*(Sachverhalt|Faits|Fatti|En fait|Ritenuto in fatto)\s*:?\s*\n", re.I)
RE_REASON = re.compile(
    r"\n\s*(Erwägungen|Erwägung|Considérant en droit|Considérants?|En droit|Diritto|Considerando in diritto|Considerando)\s*:?\s*\n", re.I)
RE_DISP = re.compile(r"(Demnach erkennt|Demnach verfügt|Demnach beschliesst|Par ces motifs|Per questi motivi)")
TITLES = (r"\b(?:Bundesrichter(?:in)?(?:nen)?|Mmes?|MM?\.|les|la|le|Juges?|fédéra(?:l|le|ux)|Giudic[ei]|federal[ei]|"
          r"Präsident(?:in)?|Président[e]?|Presidente|suppléant[e]?|nebenamtliche[rn]?|supplente|"
          r"als Einzelrichter(?:in)?|en qualité de juge unique)\b")
TOPICS = {
    "causality": r"Kausalzusammenhang|Kausalität|lien de causalité|causalité (?:naturelle|adéquate)|nesso (?:di )?causal",
    "accident_def": r"Unfallbegriff|ungewöhnliche[rn]? äussere[rn]? Faktor|notion d'accident|facteur extérieur extraordinaire|fattore esterno straordinario|unfallähnlich|assimilée? à un accident",
    "IE": r"Integritätsentschädigung|Integritätseinbusse|atteinte à l'intégrité|menomazione dell'integrità",
    "daily": r"Taggeld|indemnités? journalières?|indennità giornalier",
    "occdis": r"Berufskrankheit|maladie professionnelle|malattia professionale",
    "earnings": r"versicherte[rn]? Verdienst|gain assuré|guadagno assicurato",
    "treatment": r"Heilbehandlung|traitement médical|cura medica",
    "fallabschluss": r"Fallabschluss|clôture du cas|stabilisation de l'état de santé|Endzustand",
    "pension": r"Invalidenrente|rente d'invalidité|rendita d'invalidità|Invaliditätsgrad|taux d'invalidité",
    "expert": r"Gutachten|expertise|perizia",
}
UV_TOPICS = ["causality", "accident_def", "IE", "daily", "occdis", "earnings", "treatment", "fallabschluss"]

# Deterministic feature sets (all 0/1 except counts noted)
RUBRIC_ORIG = ["suva_party", "suva_mention", "area_uvmv", "other_insurer", "star", "five", "long25k", "granted_uv", "topics_all"]
DET_FEATURES = ["area_uvmv", "area_iv", "single", "suva_party", "other_insurer", "app_inst", "five", "star",
                "star_unknown", "obv", "uv_topics"]
DET_EXTRA = ["suva_app", "granted_uv", "principle", "suva_mention", "remand", "lang_fr", "log_cc", "bge_n", "n_consid"]


def _sw(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def split_sections(t: str) -> dict:
    """header / facts / reasoning / dispositive. Falls back gracefully on short rulings."""
    mf, md = RE_FACTS.search(t), None
    for m in RE_DISP.finditer(t):
        md = m  # last occurrence
    end = md.start() if md else len(t)
    mr = None
    for m in RE_REASON.finditer(t[:end]):
        if mf is None or m.start() > mf.start():
            mr = m
            break
    if mf and mr:
        head, facts, reasoning = t[: mf.start()], t[mf.end(): mr.start()], t[mr.end(): end]
    elif mr:
        head, facts, reasoning = t[: mr.start()], "", t[mr.end(): end]
    elif mf:
        head, facts, reasoning = t[: mf.start()], "", t[mf.end(): end]
    else:
        head, facts, reasoning = t[:2500], "", t[2500:end]
    return {"head": head, "facts": facts.strip(), "reasoning": reasoning.strip(), "dispositive": t[end:].strip()}


def _panel(h: str) -> float:
    m = re.search(r"(Besetzung|Composition|Composizione)(.*?)(Gerichtsschreiber|Greffi|Cancellier)", h, re.S)
    if not m:
        return np.nan
    seg = re.sub(TITLES, " ", m.group(2))
    return sum(1 for n in re.split(r",|\bund\b|\bet\b|\be\b", seg) if re.search(r"[A-ZÉ][a-zéèüöä]{2,}", n))


def _cls(s: str) -> str:
    s = (s or "").lower()
    if re.search(r"unfallversicherung|assurance-accident|infortuni", s):
        return "UV"
    if re.search(r"milit", s):
        return "MV"
    if re.search(r"invalidenversicherung|assurance-invalidit|invalidit", s):
        return "IV"
    return "other"


def _appellant(h: str) -> tuple[int, int]:
    m = re.search(r"(Verfahrensbeteiligte|Participants à la procédure|Partecipanti al procedimento)(.*?)"
                  r"(Beschwerdeführer(?:in)?|recourante?s?|ricorrente)\b", h, re.S)
    if not m:
        return (0, 0)
    s = m.group(2)
    if re.search(r"^\s*[A-Z]\.(?:[A-Z]\.)?_{4,}", s):
        return (0, 0)
    inst = bool(re.search(r"AG\b|SA\b|Versicher|Assurance|IV-Stelle|Office|Ufficio|Bundesamt|Caisse|Suva|Stiftung|Anstalt|Kasse|Fondation|Gemeinde|Sozial", s[:200]))
    return (int(inst), int(bool(re.search(SUVA, s))))


def build() -> pd.DataFrame:
    import psycopg

    con = psycopg.connect(DSN)
    df = pd.read_sql(
        """select r.id, r.docket, r.decision_date, r.division, r.language, r.starred, r.area, r.subject, r.outcome,
                  v.relevance, v.decision_quarter q, t.text, t.char_count cc
           from rulings r join v_relevance v on v.ruling_id=r.id
           join ruling_texts t on t.ruling_id=r.id and t.is_canonical""", con)
    gold = pd.read_sql("select r.docket, g.language, g.body from gold_summaries g join rulings r on r.id=g.ruling_id where g.is_current", con)
    gold.to_pickle(CACHE / "gold.pkl")
    sec = df.text.map(split_sections).apply(pd.Series)
    df = pd.concat([df, sec], axis=1)
    df["pos"] = (df.relevance == "relevant").astype(int)
    df["labelled"] = df.q.isin(LABELLED)
    hs = df["head"].str.extract(r"(?:Gegenstand|Objet|Oggetto)\s*\n\s*(.+)")[0]
    df["hsubj"] = hs
    df["cls"] = df.area.fillna(hs).fillna("").map(_cls)
    df["nj"] = df["head"].map(_panel)
    # --- deterministic features
    df["area_uvmv"] = df.cls.isin(["UV", "MV"]).astype(int)
    df["area_iv"] = (df.cls == "IV").astype(int)
    df["single"] = (df.nj == 1).astype(int)
    df["five"] = (df.nj >= 5).astype(int)
    df["suva_party"] = df["head"].str.contains(SUVA, regex=True).astype(int)
    df["suva_mention"] = (df.text.str.contains(SUVA, regex=True) & (df.suva_party == 0)).astype(int)
    df["other_insurer"] = ((df.cls == "UV") & (df.suva_party == 0)).astype(int)
    a = df["head"].map(_appellant)
    df["app_inst"], df["suva_app"] = a.str[0], a.str[1]
    df["star"] = (df.starred == True).astype(int)  # noqa: E712
    df["star_unknown"] = df.starred.isna().astype(int)
    df["obv"] = df.text.str.contains(
        r"offensichtlich unbegründet|manifestement (?:mal fondé|infondé)|manifestamente infondat|Art\. 109 (?:Abs\. 2|al\. 2|cpv\. 2)", regex=True).astype(int)
    df["long25k"] = (df.cc > 25000).astype(int)
    df["log_cc"] = np.log10(df.cc.clip(lower=100))
    disp = df.dispositive.str[:900]
    df["granted"] = disp.str.contains(r"gutgeheissen|est (?:partiellement )?admis|è (?:parzialmente )?accolto", regex=True).astype(int)
    df["granted_uv"] = (df.granted & ((df.area_uvmv == 1) | (df.suva_party == 1))).astype(int)
    df["remand"] = disp.str.contains(r"zurückgewiesen|renvoyée?|rinviat", regex=True).astype(int)
    df["principle"] = df.text.str.contains(
        r"Praxisänderung|Präzisierung der Rechtsprechung|changement de jurisprudence|précis(?:er|ion de) la jurisprudence|Grundsatzfrage|question de principe|noch nicht entschieden|pas encore (?:été )?tranché", regex=True).astype(int)
    for k, p in TOPICS.items():
        df["t_" + k] = df.text.str.contains(p, regex=True).astype(int)
    df["uv_topics"] = df[["t_" + k for k in UV_TOPICS]].sum(axis=1)
    df["topics_all"] = df[["t_" + k for k in TOPICS]].sum(axis=1)
    df["lang_fr"] = (df.language == "fr").astype(int)
    df["bge_n"] = df.text.str.count(r"\b(?:BGE|ATF|DTF) \d+ [IV]+ \d+")
    df["n_consid"] = df.reasoning.str.count(r"\n\s*\d+\.\d*\s")
    # --- gates
    df["g_div"] = df.division.isin(["8C", "9C"])
    df["g_area"] = df.g_div & df.cls.isin(["UV", "MV", "IV"])
    df["cand"] = df.g_area & (df.single == 0)
    return df


def load() -> pd.DataFrame:
    p = CACHE / "dataset.pkl"
    if not p.exists():
        build().to_pickle(p)
    return pd.read_pickle(p)


def gold() -> pd.DataFrame:
    load()
    return pd.read_pickle(CACHE / "gold.pkl")


# ----------------------------------------------------------------------------- evaluation
def f2_counts(tp: int, fp: int, fn: int) -> float:
    d = 5 * tp + 4 * fn + fp
    return 5 * tp / d if d else 0.0


def prf(pred: np.ndarray, y: np.ndarray, extra_fn: int = 0) -> dict:
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum()); fn = int(((~pred) & (y == 1)).sum()) + extra_fn
    return {"tp": tp, "fp": fp, "fn": fn, "kept": tp + fp,
            "recall": tp / (tp + fn) if tp + fn else 0.0, "precision": tp / (tp + fp) if tp + fp else 0.0,
            "f2": f2_counts(tp, fp, fn)}


def best_threshold(scores: np.ndarray, y: np.ndarray, extra_fn: int = 0) -> float:
    """Threshold (predict positive when score >= thr) maximising F2. Ties -> lower threshold (favours recall)."""
    best, thr = -1.0, float(np.min(scores))
    for t in np.unique(scores):
        f = prf(scores >= t, y, extra_fn)["f2"]
        if f > best + 1e-12:
            best, thr = f, float(t)
    return thr


def _oof(make_model, X: np.ndarray, y: np.ndarray, seed: int = 0, k: int = 5) -> np.ndarray:
    from sklearn.model_selection import StratifiedKFold

    out = np.zeros(len(y))
    for tr, te in StratifiedKFold(k, shuffle=True, random_state=seed).split(X, y):
        m = make_model().fit(X[tr], y[tr])
        out[te] = m.predict_proba(X[te])[:, 1]
    return out


def evaluate(df: pd.DataFrame, features: list[str], make_model, scope: str = "cand", name: str = "",
             repeats: int = 5, verbose: bool = True) -> dict:
    """Honest evaluation of a trainable scorer.

    scope: column name of a boolean mask; the model is trained and applied only inside it,
           everything outside is predicted not relevant.
    Protocols
      xq  : train on one labelled quarter, test on the other (both directions, pooled counts).
            The threshold is picked on out-of-fold training scores, never on test data.
      rcv : repeated stratified 5-fold over both labelled quarters, threshold from inner OOF.
    Returns pooled F2 / recall / precision for both, plus AP on candidates.
    """
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import StratifiedKFold

    L = df[df.labelled]
    S = L[L[scope]]
    res = {"name": name, "scope": scope, "n_feat": len(features), "n_train": len(S)}
    # --- cross-quarter
    tot = {"tp": 0, "fp": 0, "fn": 0}
    per = {}
    for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
        tr, te = S[S.q == a], S[S.q == b]
        Xtr, ytr, Xte, yte = tr[features].values.astype(float), tr.pos.values, te[features].values.astype(float), te.pos.values
        miss_tr = int(L[(L.q == a)].pos.sum() - ytr.sum()); miss_te = int(L[(L.q == b)].pos.sum() - yte.sum())
        thr = best_threshold(_oof(make_model, Xtr, ytr), ytr, miss_tr)
        s = make_model().fit(Xtr, ytr).predict_proba(Xte)[:, 1]
        r = prf(s >= thr, yte, miss_te)
        per[b] = r
        for k in tot:
            tot[k] += r[k]
    res.update({"xq_f2": f2_counts(**tot), "xq_recall": tot["tp"] / (tot["tp"] + tot["fn"]),
                "xq_precision": tot["tp"] / max(tot["tp"] + tot["fp"], 1), "xq_kept": tot["tp"] + tot["fp"],
                "xq_f2_q1": per["2026 Q1"]["f2"], "xq_f2_q4": per["2025 Q4"]["f2"]})
    # --- repeated CV
    X, y = S[features].values.astype(float), S.pos.values
    miss = int(L.pos.sum() - y.sum())
    f2s, recs, aps = [], [], []
    for rep in range(repeats):
        pred = np.zeros(len(y), bool); sc = np.zeros(len(y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(X, y):
            thr = best_threshold(_oof(make_model, X[tr], y[tr], seed=rep), y[tr], 0)
            s = make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
            pred[te] = s >= thr; sc[te] = s
        r = prf(pred, y, miss)
        f2s.append(r["f2"]); recs.append(r["recall"]); aps.append(average_precision_score(y, sc))
    res.update({"rcv_f2": float(np.mean(f2s)), "rcv_f2_sd": float(np.std(f2s)), "rcv_recall": float(np.mean(recs)),
                "ap": float(np.mean(aps))})
    if verbose:
        print(f"{name:46s} [{scope:6s} n={len(S):4d} k={len(features):2d}] "
              f"xq F2={res['xq_f2']:.3f} R={res['xq_recall']:.2f} P={res['xq_precision']:.2f} kept={res['xq_kept']:3d} "
              f"(Q1 {res['xq_f2_q1']:.3f} / Q4 {res['xq_f2_q4']:.3f}) | rcv F2={res['rcv_f2']:.3f}±{res['rcv_f2_sd']:.3f} "
              f"R={res['rcv_recall']:.2f} AP={res['ap']:.3f}")
    return res


def evaluate_fixed(df: pd.DataFrame, pred_col: str, name: str = "") -> dict:
    """Score a fixed yes/no rule (no training), pooled over both labelled quarters."""
    L = df[df.labelled]
    r = prf(L[pred_col].values.astype(bool), L.pos.values)
    print(f"{name:46s} F2={r['f2']:.3f} R={r['recall']:.2f} P={r['precision']:.2f} kept={r['kept']}")
    return {"name": name, **r}


def logreg(C: float = 1.0):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return lambda: make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight="balanced", max_iter=2000))


if __name__ == "__main__":
    (CACHE / "dataset.pkl").unlink(missing_ok=True)
    d = load()
    L = d[d.labelled]
    print("rulings", len(d), "| labelled", len(L), "pos", int(L.pos.sum()), "| cand labelled", int(L.cand.sum()),
          "pos in cand", int(L[L.cand].pos.sum()), "| Q2 cand", int(d[(d.q == '2026 Q2') & d.cand].shape[0]))
    print("sections: empty reasoning among labelled cand:", int((L[L.cand].reasoning.str.len() < 500).sum()),
          "| median reasoning chars", int(L[L.cand].reasoning.str.len().median()),
          "| median facts chars", int(L[L.cand].facts.str.len().median()))
    d["_all_cand"] = d.cand; d["_uv"] = d.cand & (d.area_uvmv == 1)
    evaluate_fixed(d, "_all_cand", "baseline: submit every candidate")
    evaluate_fixed(d, "_uv", "baseline: submit every full UV/MV ruling")
    evaluate(d, DET_FEATURES, logreg(), "cand", "logreg deterministic (cand)")
    evaluate(d, DET_FEATURES, logreg(), "g_div", "logreg deterministic (8C/9C)")
    d["_all"] = True
    evaluate(d, DET_FEATURES, logreg(), "_all", "logreg deterministic (all rulings)")

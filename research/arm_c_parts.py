"""Arm C: text parts to embed. `parts(df)` -> dict part -> (ids, texts); chunks have repeated ids."""
from __future__ import annotations
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from common import load, gold

RE_TOP = re.compile(r"(?m)^[ \t]*(\d{1,2})\.(?!\d)[ \t]*")
RE_BGG = re.compile(r"[Aa]rt\.\s*(?:42|82|83|86|89|90|91|92|93|95|96|97|99|100|105|106|107)\b(?:(?![Aa]rt\.)[^;()\n]){0,50}?(?:BGG|LTF)\b")
RE_ISSUE = re.compile(r"[Ss]treitig|litige porte|litigieu|oggetto del contendere|[Ll]itigios")
RE_COST = re.compile(r"Art\.\s*6[568]\b[^.;()]{0,40}(?:BGG|LTF)|Gerichtskosten|frais judiciaires|spese giudiziarie", re.I)


def norm(t: str) -> str:
    t = (t or "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\s*\n\s*", "\n", t).strip()


def considerations(reasoning: str) -> list[str]:
    """Split into top-level numbered considerations (1., 2., ...), accepting only sequential numbers."""
    t = norm(reasoning)
    cuts, expect = [], 1
    for m in RE_TOP.finditer(t):
        if int(m.group(1)) == expect:
            cuts.append(m.start()); expect += 1
    if not cuts:
        return [t]
    out = ([t[:cuts[0]]] if t[:cuts[0]].strip() else []) + [t[a:b] for a, b in zip(cuts, cuts[1:] + [len(t)])]
    return [c.strip() for c in out if c.strip()]


def is_boiler(c: str, pos: int, n: int) -> bool:
    refs = len(RE_BGG.findall(c))
    dens = refs / max(len(c), 1) * 1000
    if pos < 3 and refs >= 2 and dens >= 0.8 and not RE_ISSUE.search(c):
        return True          # admissibility / scope-of-review consideration
    if pos < 3 and refs >= 1 and len(c) < 500 and not RE_ISSUE.search(c):
        return True          # short "recours recevable" paragraph
    if pos == n - 1 and n > 2 and len(c) < 2000 and RE_COST.search(c):
        return True          # costs consideration
    return False


def core_reasoning(reasoning: str) -> tuple[str, list[int]]:
    cs = considerations(reasoning)
    drop = [i for i, c in enumerate(cs) if is_boiler(c, i, len(cs))]
    core = "\n".join(c for i, c in enumerate(cs) if i not in drop)
    if len(core) < 500:
        return norm(reasoning), []
    return core, drop


def chunks(text: str, size: int = 1500) -> list[str]:
    """~size-character windows cut at sentence/line ends."""
    t, out = norm(text), []
    while len(t) > size * 1.3:
        cut = max(t.rfind(". ", int(size * 0.6), size), t.rfind("\n", int(size * 0.6), size))
        cut = cut + 1 if cut > 0 else size
        out.append(t[:cut].strip()); t = t[cut:]
    if t.strip():
        out.append(t.strip())
    return out or [""]


def target_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.labelled & df.cand) | ((df.q == "2026 Q2") & df.cand) | (df.q == "2025 Q3")]


def parts(df: pd.DataFrame | None = None) -> dict:
    df = load() if df is None else df
    S = target_rows(df)
    ids = S.id.values
    P = {"subject": (ids, [norm(s) or "-" for s in S.subject.fillna(S.hsubj).fillna("")]),
         "facts": (ids, [norm(f) or norm(r)[:1500] for f, r in zip(S.facts, S.reasoning)]),
         "reasoning": (ids, [norm(r) for r in S.reasoning]),
         "core": (ids, [core_reasoning(r)[0] for r in S.reasoning])}
    cid, ctx = [], []
    for i, r in zip(ids, S.reasoning):
        for c in chunks(core_reasoning(r)[0]):
            cid.append(i); ctx.append(c)
    P["chunks"] = (np.array(cid), ctx)
    g = gold(); g = g[g.language == "de"].merge(df[["docket", "id"]], on="docket")
    P["gold"] = (g.id.values, [norm(b) for b in g.body])
    lp = Path(__file__).resolve().parent / "out" / "lessons.parquet"
    if lp.exists():
        l = pd.read_parquet(lp); l = l[l.lesson.fillna("").str.len() > 0]
        P["lesson"] = (l.id.values, [norm(x) for x in l.lesson])
    return P


if __name__ == "__main__":
    df = load(); S = target_rows(df)
    res = [core_reasoning(r) for r in S.reasoning]
    full = S.reasoning.map(lambda r: len(norm(r))).values; core = np.array([len(c) for c, _ in res])
    nd = np.array([len(d) for _, d in res])
    print(f"rulings {len(S)} | median chars full {int(np.median(full))} core {int(np.median(core))} | "
          f"dropped considerations: mean {nd.mean():.2f}, none dropped in {int((nd == 0).sum())} rulings")
    print("chunks total", len(parts(df)["chunks"][1]))
    for j in [0, 40, 120, 200, 300]:
        r = S.iloc[j]; cs = considerations(r.reasoning); _, drop = core_reasoning(r.reasoning)
        print(f"\n=== {r.docket} ({r.language}) {len(cs)} considerations, dropped {drop}")
        for i, c in enumerate(cs):
            print(f"  [{'DROP' if i in drop else 'keep'}] {len(c):6d}ch bgg={len(RE_BGG.findall(c))} | {c[:150]!r}")

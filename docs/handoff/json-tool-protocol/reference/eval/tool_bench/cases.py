# SPDX-License-Identifier: Apache-2.0
# Case design adapted from ArchAI's tool_bench (kirtanp/hackpertus-archives, src/archai/tool_bench.py),
# Copyright (c) 2026 The ArchAI contributors, MIT License: BFCL categories (simple, parallel,
# parallel_multiple, irrelevance), one request per case, templated instructions per language, values
# drawn from the data with a fixed seed. Added here: Italian, a closed id set per ruling, act aliases,
# and the "evidence" category (the pipeline's own shape). See NOTICE.
"""Benchmark cases built from public ruling records, deterministically (seeded).

Input records need only ``docket``, ``language`` (or ``lang``) and ``considerations``
``[{id, e_number, text}]`` (or a ``text`` that :func:`split_considerations` can split). A
consideration without ``id`` gets ``c1``, ``c2`` ... in order; ``e_number`` may also be given as
``number``. Case ids are derived from the case content, so the same case has the same id in every
run and profile. **Every other
field is dropped on load** (labels, summaries or any Suva-derived field never enter a case: D-031).
Use public rulings only; the cases file holds short excerpts of them (evidence category).

Categories:

* ``simple``: one instruction, one correct call (one per tool and language).
* ``parallel``: the same tool on two values in one turn.
* ``parallel_multiple``: two different tools in one turn.
* ``irrelevance``: no tool fits; the correct answer is no call.
* ``evidence``: the pipeline's shape: choose the consideration that contains a quoted passage, or
  ``none`` when the passage comes from another ruling. Gold is computed by code (the passage occurs
  in exactly one consideration), never by a model.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .tools import ACTS

LANGS = ("de", "fr", "it")
_ACT_BY_LANG = {  # how a lawyer writes the act in each language
    "UVG": {"de": "UVG", "fr": "LAA", "it": "LAINF"},
    "ATSG": {"de": "ATSG", "fr": "LPGA", "it": "LPGA"},
    "UVV": {"de": "UVV", "fr": "OLAA", "it": "OAINF"},
    "IVG": {"de": "IVG", "fr": "LAI", "it": "LAI"},
    "BV": {"de": "BV", "fr": "Cst.", "it": "Cost."},
}
assert set(_ACT_BY_LANG) == set(ACTS)

T = {
    "get": {"de": "Zeig mir den Wortlaut von E. {e}.", "fr": "Montre-moi le texte du consid. {e}.",
            "it": "Mostrami il testo del consid. {e}."},
    "ruling": {"de": "Hol das Urteil {d}.", "fr": "Récupère l'arrêt {d}.", "it": "Recupera la sentenza {d}."},
    "article": {"de": "Was steht in Art. {n} {act}?", "fr": "Que dit l'art. {n} {act} ?",
                "it": "Cosa dice l'art. {n} {act}?"},
    "get2": {"de": "Zeig mir E. {a} und E. {b}.", "fr": "Montre-moi les consid. {a} et {b}.",
             "it": "Mostrami i consid. {a} e {b}."},
    "ruling2": {"de": "Hol die Urteile {a} und {b}.", "fr": "Récupère les arrêts {a} et {b}.",
                "it": "Recupera le sentenze {a} e {b}."},
    "get_article": {"de": "Zeig mir E. {e} und was Art. {n} {act} sagt.",
                    "fr": "Montre-moi le consid. {e} et ce que dit l'art. {n} {act}.",
                    "it": "Mostrami il consid. {e} e cosa dice l'art. {n} {act}."},
    "ruling_article": {"de": "Hol das Urteil {d} und sag mir, was Art. {n} {act} regelt.",
                       "fr": "Récupère l'arrêt {d} et dis-moi ce que règle l'art. {n} {act}.",
                       "it": "Recupera la sentenza {d} e dimmi cosa disciplina l'art. {n} {act}."},
    "locate": {"de": "Welche Erwägung enthält wörtlich diese Stelle: «{p}»?",
               "fr": "Quel considérant contient mot pour mot ce passage : « {p} » ?",
               "it": "Quale considerando contiene testualmente questo passaggio: «{p}»?"},
}
IRRELEVANT = {
    "de": ["Wie wird das Wetter morgen in Bern?", "Schreib ein kurzes Gedicht über den Herbst.",
           "Übersetze das Wort «Unfall» ins Englische.", "Wie spät ist es gerade?",
           "Wer hat die Fussball-WM 2014 gewonnen?"],
    "fr": ["Quel temps fera-t-il demain à Lausanne ?", "Écris un court poème sur l'automne.",
           "Traduis le mot « accident » en anglais.", "Quelle heure est-il ?",
           "Qui a gagné la Coupe du monde de football 1998 ?"],
    "it": ["Che tempo farà domani a Lugano?", "Scrivi una breve poesia sull'autunno.",
           "Traduci la parola «infortunio» in inglese.", "Che ore sono adesso?",
           "Chi ha vinto i Mondiali di calcio del 2006?"],
}

#: Cases per language (``simple`` is per tool and language). ``quick``: a smoke run (~30 cases);
#: ``full``: the measurement (~135 cases). Evidence carries the decision, so it gets the most cases.
PROFILES: dict[str, dict[str, int]] = {
    "quick": {"simple": 1, "parallel": 1, "parallel_multiple": 1, "irrelevance": 2, "evidence_present": 2,
              "evidence_absent": 1},
    "full": {"simple": 4, "parallel": 4, "parallel_multiple": 4, "irrelevance": 5, "evidence_present": 16,
             "evidence_absent": 4},
}
EXCERPT_CHARS = 400
MAX_CONSIDERATIONS = 24
PASSAGE_WORDS = 10

_KEEP = ("docket", "language", "lang", "considerations", "text")
_START = re.compile(r"(?:Erwägungen?|Considérant(?:s)?(?: en droit)?|Considerando(?: in diritto)?|Considerandi)\s*:",
                    re.I)
_END = re.compile(r"Demnach erkennt das Bundesgericht|Par ces motifs|Per questi motivi", re.I)
_NUM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?=\S)", re.M)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("­", "")
    return re.sub(r"\s+", " ", s).strip().casefold()


def split_considerations(text: str) -> list[dict[str, str]]:
    """Fallback splitter for a raw ruling text: numbered paragraphs after the 'Erwägungen:' heading.

    The repository's own splitter (crawl stage) is authoritative; this one only lets the benchmark
    run on records that carry the plain text. Returns ``[]`` when the structure is not recognised.
    """
    m = _START.search(text)
    if not m:
        return []
    body = text[m.end():]
    end = _END.search(body)
    body = body[: end.start()] if end else body
    marks = list(_NUM.finditer(body))
    out = []
    for i, mk in enumerate(marks):
        chunk = body[mk.end(): marks[i + 1].start() if i + 1 < len(marks) else len(body)].strip()
        if chunk:
            out.append({"id": f"c{len(out) + 1}", "e_number": mk.group(1), "text": chunk})
    return out


def load_rulings(path: str | Path) -> list[dict[str, Any]]:
    """Read ruling records (JSONL), keep only the allowed fields, split considerations if needed."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rec = {k: raw[k] for k in _KEEP if k in raw}
        lang = (rec.get("language") or rec.get("lang") or "").lower()[:2]
        cons = rec.get("considerations") or split_considerations(rec.get("text") or "")
        cons = [{"id": str(c.get("id") or f"c{i + 1}"), "e_number": str(c.get("e_number") or c.get("number") or ""),
                 "text": c.get("text") or ""} for i, c in enumerate(cons) if isinstance(c, Mapping)]
        if rec.get("docket") and lang in LANGS and len(cons) >= 3:
            out.append({"docket": rec["docket"], "language": lang, "considerations": cons})
    return out


def ruling_index(ruling: Mapping[str, Any]) -> str:
    """The data block of the call categories: ids and court numbers only (no text, cheap)."""
    items = [f"[{c['id']}] E. {c['e_number']}" for c in ruling["considerations"][:MAX_CONSIDERATIONS]]
    return f"Ruling {ruling['docket']}. Considerations: " + " | ".join(items)


def excerpts(ruling: Mapping[str, Any]) -> list[dict[str, str]]:
    """The considerations shown in the evidence category, each cut to ``EXCERPT_CHARS``."""
    return [{"id": c["id"], "e_number": c["e_number"], "text": re.sub(r"\s+", " ", c["text"])[:EXCERPT_CHARS]}
            for c in ruling["considerations"][:MAX_CONSIDERATIONS]]


def _unique_passage(rnd: random.Random, shown: Sequence[Mapping[str, str]]) -> tuple[str, str] | None:
    order = list(range(len(shown)))
    rnd.shuffle(order)
    for i in order:
        words = shown[i]["text"].split()
        if len(words) < PASSAGE_WORDS + 4:
            continue
        for _ in range(6):
            start = rnd.randrange(0, len(words) - PASSAGE_WORDS - 1)  # never the cut-off last word
            p = " ".join(words[start:start + PASSAGE_WORDS])
            hits = [c["id"] for c in shown if _norm(p) in _norm(c["text"])]
            if hits == [shown[i]["id"]] and not re.search(r"[«»\"<>|]", p):
                return p, shown[i]["id"]
    return None


def _pick_e(rnd: random.Random, ruling: Mapping[str, Any], k: int) -> list[dict[str, str]]:
    cands = [c for c in ruling["considerations"][:MAX_CONSIDERATIONS] if c["e_number"]]
    nums = [c["e_number"] for c in cands]
    cands = [c for c in cands if nums.count(c["e_number"]) == 1]
    return rnd.sample(cands, k) if len(cands) >= k else []


def build_cases(rulings: Sequence[Mapping[str, Any]], profile: str = "full", seed: int = 5,
                langs: Iterable[str] = LANGS) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(cases, warnings)``. Same rulings, profile and seed: same cases, byte for byte."""
    size = PROFILES[profile]
    rnd = random.Random(seed)
    cases: list[dict[str, Any]] = []
    warnings: list[str] = []
    dockets = sorted({r["docket"] for r in rulings})
    if len(rulings) < 2:
        raise ValueError("the benchmark needs at least 2 rulings")

    def add(cat: str, lang: str, q: str, gold: Any, ruling: Mapping[str, Any] | None, data: str | None) -> bool:
        # Content-derived id: stable across runs, profiles and code changes that do not change the case.
        digest = hashlib.sha256(json.dumps([cat, lang, q, gold, ruling["docket"] if ruling else None, data],
                                           ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        cid = f"{cat}-{lang}-{digest}"
        if any(c["id"] == cid for c in cases):
            return False  # the same case drawn twice: keep one
        cases.append({"id": cid, "category": cat, "lang": lang, "q": q,
                      "docket": ruling["docket"] if ruling else None, "data": data, "gold": gold,
                      "considerations": [{"id": c["id"], "e_number": c["e_number"]}
                                         for c in ruling["considerations"][:MAX_CONSIDERATIONS]] if ruling else None})
        return True

    def act() -> tuple[str, str]:
        a = rnd.choice(sorted(ACTS))
        return a, str(rnd.randint(1, 120))

    for lang in langs:
        same_lang = [r for r in rulings if r["language"] == lang]
        for _ in range(size["simple"]):
            r = rnd.choice(rulings)
            picked = _pick_e(rnd, r, 1)
            if picked:
                c = picked[0]
                add("simple", lang, T["get"][lang].format(e=c["e_number"]), [["get_consideration", {"a_id": c["id"]}]],
                    r, ruling_index(r))
            d = rnd.choice(dockets)
            add("simple", lang, T["ruling"][lang].format(d=d), [["lookup_ruling", {"a_docket": d}]], None, None)
            a, n = act()
            add("simple", lang, T["article"][lang].format(n=n, act=_ACT_BY_LANG[a][lang]),
                [["find_article", {"a_act": a, "b_number": n}]], None, None)
        for i in range(size["parallel"]):
            if i % 2 == 0:
                r = rnd.choice(rulings)
                two = _pick_e(rnd, r, 2)
                if two:
                    add("parallel", lang, T["get2"][lang].format(a=two[0]["e_number"], b=two[1]["e_number"]),
                        [["get_consideration", {"a_id": c["id"]}] for c in two], r, ruling_index(r))
                    continue
            d1, d2 = rnd.sample(dockets, 2)
            add("parallel", lang, T["ruling2"][lang].format(a=d1, b=d2),
                [["lookup_ruling", {"a_docket": d1}], ["lookup_ruling", {"a_docket": d2}]], None, None)
        for i in range(size["parallel_multiple"]):
            a, n = act()
            r = rnd.choice(rulings)
            picked = _pick_e(rnd, r, 1)
            if i % 2 == 0 and picked:
                add("parallel_multiple", lang, T["get_article"][lang].format(e=picked[0]["e_number"], n=n,
                                                                             act=_ACT_BY_LANG[a][lang]),
                    [["get_consideration", {"a_id": picked[0]["id"]}], ["find_article", {"a_act": a, "b_number": n}]],
                    r, ruling_index(r))
            else:
                d = rnd.choice(dockets)
                add("parallel_multiple", lang, T["ruling_article"][lang].format(d=d, n=n, act=_ACT_BY_LANG[a][lang]),
                    [["lookup_ruling", {"a_docket": d}], ["find_article", {"a_act": a, "b_number": n}]], None, None)
        for q in rnd.sample(IRRELEVANT[lang], min(size["irrelevance"], len(IRRELEVANT[lang]))):
            add("irrelevance", lang, q, [], None, None)
        if not same_lang:
            warnings.append(f"evidence/{lang}: no {lang} ruling in the input; no evidence case for {lang}")
            continue
        for kind in ("present", "absent"):
            made = tries = 0
            while made < size[f"evidence_{kind}"] and tries < 50 * size[f"evidence_{kind}"]:
                tries += 1
                r = rnd.choice(same_lang)
                shown = excerpts(r)
                if kind == "present":
                    hit = _unique_passage(rnd, shown)
                    if not hit:
                        continue
                    passage, gold = hit
                else:
                    others = [o for o in same_lang if o["docket"] != r["docket"]] or [o for o in rulings if o is not r]
                    hit = _unique_passage(rnd, excerpts(rnd.choice(others)))
                    if not hit or any(_norm(hit[0]) in _norm(c["text"]) for c in shown):
                        continue
                    passage, gold = hit[0], "none"
                data = "\n".join(f"[{c['id']}] E. {c['e_number']}: {c['text']}" for c in shown)
                if add("evidence", lang, T["locate"][lang].format(p=passage), {"a_consideration": gold}, r, data):
                    made += 1
            if made < size[f"evidence_{kind}"]:
                warnings.append(f"evidence/{lang}/{kind}: built {made} of {size[f'evidence_{kind}']} cases")
    return cases, warnings

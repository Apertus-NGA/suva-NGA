# SPDX-License-Identifier: Apache-2.0
"""Synthetic rulings and scripted gateways for the offline benchmark tests (G9: every mock declared here)."""
from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from typing import Any

from llm.tool_protocol import ChatReply, ChatRequest

WORDS = {
    "de": "Versicherte Unfall Leistung Rente Taggeld Kausalzusammenhang Gutachten Arbeitsunfähigkeit Vorinstanz "
          "Beschwerde Suva Integritätsentschädigung Heilbehandlung Invalidität Einkommen Abklärung Bericht".split(),
    "fr": "assuré accident prestation rente indemnité causalité expertise incapacité instance recours "
          "atteinte traitement invalidité revenu instruction rapport".split(),
    "it": "assicurato infortunio prestazione rendita indennità causalità perizia incapacità istanza ricorso "
          "menomazione cura invalidità reddito accertamento rapporto".split(),
}


def synthetic_rulings(per_lang: int = 3, considerations: int = 7, seed: int = 1) -> list[dict[str, Any]]:
    """Made-up ruling records: random words, real-looking numbering, no real text."""
    rnd = random.Random(seed)
    out = []
    for lang, words in WORDS.items():
        for _ in range(per_lang):
            cons = []
            for j in range(considerations):
                num = f"{j + 1}" if j % 3 == 0 else f"{j // 3 + 1}.{j % 3}"
                text = " ".join(rnd.choice(words) + str(rnd.randint(1, 999)) for _ in range(80))
                cons.append({"id": f"c{j + 1}", "e_number": num, "text": text})
            out.append({"docket": f"8C_{100 + len(out)}/2025", "language": lang, "considerations": cons,
                        "label": "MUST_NOT_LEAK", "suva_summary": "MUST_NOT_LEAK"})
    return out


def _case_for(req: ChatRequest, cases: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    user = req.messages[1]["content"]  # the original user turn (a repair turn comes after it)
    hits = [c for c in cases if user.endswith(c["q"])]
    assert len(hits) == 1, "each case question must identify its case"
    return hits[0]


def _e_number(case: Mapping[str, Any], cid: str) -> str:
    return next(c["e_number"] for c in case["considerations"] if c["id"] == cid)


def make_gateway(cases: Sequence[Mapping[str, Any]], style: str = "oracle"):
    """A factory ``model -> ChatFn`` answering every case.

    ``oracle``: the gold answer, canonical ids. ``noisy``: the gold answer written the way models
    slip (court numbers instead of ids, French act names, fences). ``garbage``: prose, no JSON, no call.
    ``overeager``: oracle, except that irrelevance cases get a call anyway (an invented tool natively,
    an invalid ``find_article`` in JSON). ``text``: oracle, except that native evidence replies answer
    in plain text (``E. <number>``) instead of calling the tool.
    """
    def chat(req: ChatRequest) -> ChatReply:
        case = _case_for(req, cases)
        gold = case["gold"]
        calls = [["locate_passage", gold]] if case["category"] == "evidence" else gold
        if style == "garbage":
            return ChatReply("I cannot help with that.", "stop", "apertus-v1-5-70b")
        if style == "overeager" and case["category"] == "irrelevance":
            calls = [["translate", {"text": "x"}]] if req.tools else [["find_article", {"a_act": "none",
                                                                                       "b_number": "none"}]]
        if style == "text" and req.tools and case["category"] == "evidence":
            cid = gold["a_consideration"]
            return ChatReply("none" if cid == "none" else "E. " + _e_number(case, cid), "stop", "apertus-v1-5-70b")
        if style == "noisy":
            noisy = []
            for name, args in calls:
                a = dict(args)
                if "a_id" in a:
                    a["a_id"] = "E. " + _e_number(case, a["a_id"])
                if a.get("a_consideration") not in (None, "none"):
                    a["a_consideration"] = "E. " + _e_number(case, a["a_consideration"])
                if a.get("a_act") == "UVG":
                    a["a_act"] = "LAA"
                noisy.append([name, a])
            calls = noisy
        if req.tools:
            tc = tuple({"id": f"call_{i}", "type": "function",
                        "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                       for i, (n, a) in enumerate(calls))
            return ChatReply(None, "tool_calls", "apertus-v1-5-70b", tc)
        if case["category"] == "evidence":
            body = json.dumps(calls[0][1], ensure_ascii=False)
        else:
            body = json.dumps({"a_calls": [{"a_tool": n, "b_args": a} for n, a in calls]
                               or [{"a_tool": "finish", "b_args": {}}]}, ensure_ascii=False)
        return ChatReply("```json\n" + body + "\n```" if style == "noisy" else body, "stop", "apertus-v1-5-70b")

    return lambda model: chat

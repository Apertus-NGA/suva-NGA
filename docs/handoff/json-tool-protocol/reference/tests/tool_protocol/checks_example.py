# SPDX-License-Identifier: Apache-2.0
"""An example grounding check, the shape ``src/verify/`` implements (S7). Used by the tests only."""
import re
import unicodedata

from llm.tool_protocol import NONE_ID, Problem


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("­", "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("„", '"').replace("«", '"').replace("»", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def quote_in_cited(obj, ruling):
    """TAG_SIGNAL: the quote is in the cited consideration (normalised), and the value is in the quote."""
    cid = obj["a_consideration"]
    if cid == NONE_ID:
        return [] if not obj["b_quote"].strip() and not obj["c_value"].strip() else [
            Problem("b_quote", "abstention_with_content", "'none' needs an empty quote and value")]
    text = {c["id"]: c["text"] for c in ruling["considerations"]}[cid]
    problems = []
    if not obj["b_quote"].strip() or norm(obj["b_quote"]) not in norm(text):
        problems.append(Problem("b_quote", "quote_not_in_source",
                                "the quote is not verbatim in the cited consideration"))
    elif norm(obj["c_value"]) not in norm(obj["b_quote"]):
        problems.append(Problem("c_value", "value_not_in_quote", "the value must be copied from the quote"))
    return problems

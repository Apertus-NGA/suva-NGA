# SPDX-License-Identifier: Apache-2.0
"""The benchmark's tools: small, read-only, domain-shaped, with closed id sets.

Three call tools (``get_consideration``, ``lookup_ruling``, ``find_article``) for the BFCL-style
categories, and one form tool (``locate_passage``) for the evidence category, which is the shape the
pipeline actually uses (choose one offered id, or ``none``). Handlers return canned strings: the
benchmark measures the *choice of calls*, not what the tools return, and never touches a network.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from llm.tool_protocol import IdTable, Tool, bind_enums, consideration_table, strict_profile

#: Federal acts offered to find_article, by their German abbreviation (the canonical value), with the
#: French and Italian abbreviations accepted as aliases by code. In STRICT mode the enum forces the
#: German value; in the other modes the IdTable maps an alias, and the raw score counts it as a miss.
ACTS: dict[str, list[str]] = {
    "UVG": ["LAA", "LAINF"],
    "ATSG": ["LPGA"],
    "UVV": ["OLAA", "OAINF"],
    "IVG": ["LAI"],
    "BV": ["Cst.", "Cost."],
}
ACT_TABLE = IdTable(list(ACTS), ACTS)


def _canned(args: Mapping[str, Any], ctx: Any) -> str:
    return "ok"


GET_CONSIDERATION = Tool(
    "get_consideration",
    "Return the full text of one consideration of the ruling shown in the data, by its id in square brackets.",
    {"type": "object", "properties": {"a_id": {"type": "string"}}, "additionalProperties": False,
     "required": ["a_id"]},
    handler=_canned,
)
LOOKUP_RULING = Tool(
    "lookup_ruling",
    "Fetch another Federal Supreme Court ruling by its docket number, as written in the request.",
    {"type": "object", "properties": {"a_docket": {"type": "string", "maxLength": 40}}, "additionalProperties": False,
     "required": ["a_docket"]},
    handler=_canned,
)
FIND_ARTICLE = Tool(
    "find_article",
    "Return the text of one article of a Swiss federal act. Give the act's German abbreviation and the article number.",
    {"type": "object", "properties": {"a_act": {"type": "string", "enum": list(ACTS)},
                                      "b_number": {"type": "string", "maxLength": 12}},
     "additionalProperties": False, "required": ["a_act", "b_number"]},
    handler=_canned,
)
CALL_TOOLS: tuple[Tool, ...] = (GET_CONSIDERATION, LOOKUP_RULING, FIND_ARTICLE)

LOCATE_PASSAGE = Tool(
    "locate_passage",
    "Choose the consideration that contains the quoted passage word for word. "
    "Choose none if no consideration contains it.",
    {"type": "object", "properties": {"a_consideration": {"type": "string"}}, "additionalProperties": False,
     "required": ["a_consideration"]},
)


def id_tables_for(considerations: Sequence[Mapping[str, str]]) -> dict[str, dict[str, IdTable]]:
    """Per-tool id tables for one ruling, in the shape :func:`run_tools` takes."""
    return {"get_consideration": {"a_id": consideration_table(considerations)}, "find_article": {"a_act": ACT_TABLE}}


def native_tool_specs(tools: Sequence[Tool], id_tables: Mapping[str, Mapping[str, IdTable]]) -> list[dict[str, Any]]:
    """OpenAI ``tools`` entries for the native configurations, with the same enums as the JSON ones."""
    specs = []
    for t in tools:
        params = bind_enums(t.parameters, {p: tb.ids for p, tb in id_tables.get(t.name, {}).items()})
        specs.append({"type": "function", "function": {"name": t.name, "description": t.description,
                                                       "parameters": strict_profile(params)}})
    return specs


def norm_docket(s: str) -> str:
    """``8c 123/2025`` and ``8C_123/2025`` are the same docket."""
    return re.sub(r"[\s._]+", "_", s.strip().upper())


def norm_article(s: str) -> str:
    """``Art. 6``, ``art 6``, ``6`` are article 6; paragraph details are not part of the gold."""
    s = re.sub(r"^(?:art(?:icle|ikel|icolo)?\.?\s*)", "", s.strip(), flags=re.I)
    return s.split()[0].rstrip(".,;") if s else s

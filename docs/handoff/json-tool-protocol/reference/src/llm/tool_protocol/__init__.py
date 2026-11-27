# SPDX-License-Identifier: Apache-2.0
"""JSON tool protocol for Apertus: the model proposes typed JSON, code validates and decides.

Public API (see README.md in this folder for the design, usage and rules):

* :func:`propose`: one structured proposal (what the pipeline uses).
* :func:`run_tools`: a bounded loop of read-only tool calls (benchmark, later features).
* :class:`Tool`, :class:`Tier`: tool specification and the JSON cascade tiers.
* :func:`consideration_table`, :class:`IdTable`: closed id sets the model may choose from.
* :func:`parse_object`, :func:`validate`: the building blocks, usable on stored raw outputs
  (offline re-verification and replay tests).
"""
from .ids import NONE_ID, IdTable, Resolution, consideration_table
from .parse import ParseResult, parse_object
from .prompting import delimit, format_block, neutralise, new_nonce, repair_message
from .protocol import (
    CallRecord,
    ChatFn,
    ChatReply,
    ChatRequest,
    LoopOutcome,
    Outcome,
    RequestRejected,
    TransportFailure,
    propose,
    run_tools,
)
from .schema import (
    FINISH,
    SUPPORTED_KEYWORDS,
    Tier,
    Tool,
    bind_enums,
    inline_refs,
    lint_strict,
    loop_schema,
    placeholder_example,
    response_format,
    strict_profile,
    unsupported_keywords,
)
from .validate import Problem, Validation, drop_items, validate

__all__ = [
    "IdTable", "Resolution", "consideration_table", "NONE_ID", "ParseResult", "parse_object",
    "delimit", "format_block", "neutralise", "new_nonce", "repair_message",
    "CallRecord", "ChatFn", "ChatReply", "ChatRequest", "LoopOutcome", "Outcome", "RequestRejected",
    "TransportFailure", "propose", "run_tools", "FINISH", "Tier", "Tool", "bind_enums", "lint_strict",
    "loop_schema", "placeholder_example", "response_format", "strict_profile", "Problem", "Validation",
    "drop_items", "validate", "inline_refs", "unsupported_keywords", "SUPPORTED_KEYWORDS",
]
#: 0.1.0: the 27 Nov smoke. 0.2.0: after the adversarial review ($ref/anyOf validation, code-only
#: constraints, fail-closed checks, linear parser, whitespace runaway, cache_salt). 0.2.1: the package is
#: unchanged; the benchmark salts every live run (run_id), counts cache hits and needs --limit or --all.
__version__ = "0.2.1"

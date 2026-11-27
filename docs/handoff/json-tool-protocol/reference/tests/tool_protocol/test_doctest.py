# SPDX-License-Identifier: Apache-2.0
"""The docstring examples run with the suite (no separate ``--doctest-modules`` path to forget)."""
import doctest

import llm.tool_protocol.parse as parse


def test_parse_docstring_examples():
    result = doctest.testmod(parse, optionflags=doctest.ELLIPSIS)
    assert result.attempted >= 1 and result.failed == 0

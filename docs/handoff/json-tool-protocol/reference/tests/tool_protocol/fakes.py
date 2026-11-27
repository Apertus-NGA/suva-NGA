# SPDX-License-Identifier: Apache-2.0
"""Scripted chat functions for offline tests. Every mock is declared here (golden rule G9)."""
from __future__ import annotations

from collections.abc import Sequence

from llm.tool_protocol import ChatReply, ChatRequest, RequestRejected, TransportFailure


class ScriptedChat:
    """Returns the scripted replies in order and records every request it received.

    A script item is a ``ChatReply``, a ``str`` (content with finish_reason "stop"), an exception
    instance to raise, or a callable ``request -> ChatReply``.
    """

    def __init__(self, script: Sequence[object]):
        self.script = list(script)
        self.requests: list[ChatRequest] = []

    def __call__(self, req: ChatRequest) -> ChatReply:
        self.requests.append(req)
        if not self.script:
            raise AssertionError("the protocol made more calls than scripted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ChatReply):
            return item
        if isinstance(item, str):
            return ChatReply(item, "stop", "apertus-v1-5-70b")
        if callable(item):
            return item(req)
        raise TypeError(item)


__all__ = ["ScriptedChat", "RequestRejected", "TransportFailure", "ChatReply"]

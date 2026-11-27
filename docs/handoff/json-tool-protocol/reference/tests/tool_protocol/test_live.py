# SPDX-License-Identifier: Apache-2.0
"""Live contract checks on the gateway (``RUN_LIVE=1 pytest -m live``; excluded from ``make check``).

Each contract is sent once per model through the project's client, on a synthetic ruling (no real
text, no Suva material), and must come back usable (``ok`` or ``ok_repaired``) in the STRICT tier.
The number of attempts is printed (``RUN_LIVE=1 pytest -m live -s``), so a run can report how many passed at
the first attempt. These tests check the **format** round trip only (shape, ids, the quote check of
``tag_signal``); they say nothing about the content (for example which party appealed): content is
measured by the evaluation, not here. ``make smoke-llm`` runs them, after the client's own probe.

They run only when asked twice: the ``live`` marker (``pytest -m live``) **and** ``RUN_LIVE=1``, so
a test command that passes its own ``-m`` cannot reach the gateway by accident. Each session sends
its own ``cache_salt`` (``LIVE_SALT``, or a timestamp), so the client's replay cache cannot answer
for the gateway; a reply the client marks ``REPLAY`` fails the test.

``LIVE_CHAT_FACTORY`` names ``module:factory`` with ``factory(model) -> ChatFn``. The default is the
project client, ``llm.client:chat_fn``; the reference tree of the handoff (never a repo clone, G2)
sets ``LIVE_CHAT_FACTORY=examples.chatfn_mapping:make_chat_fn``. ``LIVE_MODELS`` is a space-separated
list.
"""
import importlib
import os
from datetime import datetime, timezone

import pytest

from llm.tool_protocol import Tier, consideration_table, delimit, new_nonce, propose

from .checks_example import quote_in_cited
from .contracts import JUSTIFY, SUMMARY, TAG_SIGNAL

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live gateway test: set RUN_LIVE=1")]
SALT = os.environ.get("LIVE_SALT") or "live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

RULING = {"considerations": [
    {"id": "c1", "e_number": "1", "text": "Die Beschwerde in öffentlich-rechtlichen Angelegenheiten ist zulässig."},
    {"id": "c2", "e_number": "3.1", "text": "Streitig ist der Anspruch auf eine Integritätsentschädigung."},
    {"id": "c3", "e_number": "3.2", "text": "Die Integritätseinbusse beträgt 15 Prozent gemäss Gutachten."},
    {"id": "c4", "e_number": "4", "text": "Die Beschwerde wird abgewiesen."},
]}
DATA = "\n".join(f"[{c['id']}] E. {c['e_number']}: {c['text']}" for c in RULING["considerations"])
MODELS = os.environ.get("LIVE_MODELS", "apertus-v1-5-70b apertus-v1-5-8b").split()


def _factory():
    mod, _, attr = os.environ.get("LIVE_CHAT_FACTORY", "llm.client:chat_fn").partition(":")
    return getattr(importlib.import_module(mod), attr)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("tool, tables, checks, question", [
    (JUSTIFY, {"a_evidence[]": consideration_table(RULING["considerations"])}, [],
     "Is this ruling relevant for an accident insurer? Cite the considerations."),
    (TAG_SIGNAL, {"a_consideration": consideration_table(RULING["considerations"], none_option=True)},
     [quote_in_cited], "Fact asked: the integrity loss rate in percent."),
    (SUMMARY, {"a_claims[].a_cites[]": consideration_table(RULING["considerations"])}, [],
     "Summarise the ruling as claims."),
], ids=["justify", "tag_signal", "summary"])
def test_contract_round_trip_on_the_gateway(model, tool, tables, checks, question):
    chat, modes = _factory()(model), []

    def recording(req):
        reply = chat(req)
        modes.append(reply.mode)
        return reply

    out = propose(recording, tool, system="You read Swiss Federal Supreme Court rulings.",
                  user=delimit("ruling", DATA, new_nonce(DATA)) + "\n\n" + question, purpose="live_contract",
                  prompt_version="live-1", tier=Tier.STRICT, id_tables=tables, checks=checks, context=RULING,
                  item_level=["a_claims"] if tool is SUMMARY else (), max_tokens=600, cache_salt=SALT)
    print(f"\n{model} {tool.name}: {out.status}, attempts {out.attempts}, dropped {len(out.dropped)}")
    assert "REPLAY" not in modes, "served from the client's replay cache: not a live check"
    assert out.ok, (out.reason, [p.code for p in out.problems], out.trace)
    assert out.tier is Tier.STRICT

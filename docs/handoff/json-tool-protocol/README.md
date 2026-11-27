# JSON tool protocol: handoff (reference v0.2.1)

Reference documentation for the `tool-calling` area: Apertus tool calling through a JSON
protocol (D-058, which lands in the area's first PR). Nothing here is imported or run by the
pipeline, and `make check` does not lint it. The lead committed it on 27 Nov 2026 so that the
team and the next agent can implement it from the repository.

- **Start or resume an agent:** `REONBOARD.md`. Its prompt first establishes where the work
  stands. `BOOTSTRAP.md` is the original first-start procedure.
- **Reference:** `HANDOFF.md`. The role brief is `reference/docs/agents/tool-calling.md`; it lands
  as `docs/agents/tool-calling.md` in the area's first PR.
- **Implementation:** `reference/` mirrors the repository's paths. It is Apache-2.0, with parts
  adapted from ArchAI under the MIT licence, credited in `NOTICE.fragment` and in each file's
  header. The import PR copies it into `src/`, `eval/` and `tests/`; nothing imports it from
  here.
- **Left out of this copy:** `upstream/` and `reference/examples/`, which read the key or call
  the gateway outside `src/llm/` (G2), and `smoke/`, a smoke run on DS7 that is never evidence
  (EVAL §3b). They stay in the original archive, outside the repository.
- **Where the brief and `BOOTSTRAP.md` say** the handoff sits in `tmp/json-tool-protocol/` and is
  never committed, read this folder instead. The rule that remains: never copy `upstream/`,
  `examples/`, `smoke/` or the reference `conftest.py` into the code tree.
- **Status:** not implemented. In its own tree: 263 tests passed, 1 skipped, 6 live tests
  deselected. After the port, the two tool test paths should give 246 passed, 1 skipped,
  6 deselected.

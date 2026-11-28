"""HTTP API for the legal-expert UI and for the judges (docs/API.md, D-091).

Reads the data layer of `src/db/sql/` (corpus, triage, gold, summ, ops) and writes only through its SECURITY DEFINER
functions. Launches the existing pipeline steps (layer 1, layer 2) as subprocesses; it never decides relevance.
"""

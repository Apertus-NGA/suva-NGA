"""The single gateway to Apertus (AGENTS.md G2): every call to LLM_BASE_URL goes through this package.

Modules: `config` (environment, G3), `served_model` (allow-list of MODELS.md §1), `probe` (`make smoke-llm`),
`client` (the Apertus client). No network call at import.
"""

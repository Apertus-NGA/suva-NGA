"""Where the two fiche-prompt versions live.

v1  src/summarize/v1/   one glossary and one prompt for every ruling.
v2  src/summarize/v2/   one glossary and one prompt per matter. This is the one that runs.
"""

if __package__:
    from .v2.prompts import VERSION, category_of, glossary_block, sigil_hint, sigils, system_prompt
else:
    from v2.prompts import VERSION, category_of, glossary_block, sigil_hint, sigils, system_prompt

__all__ = [
    "VERSION",
    "category_of",
    "glossary_block",
    "sigil_hint",
    "sigils",
    "system_prompt",
]

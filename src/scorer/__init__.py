"""The Suva Scout relevance scorer on the six-schema database (D-094).

Layer 2 V2.0.0 is the sign-constrained scorer over twelve rules (eleven facts read by code and one consensus of six
Apertus 70B readings). The ranking step V1.0.0 marks the rulings the scorer's run promoted. Both are loaded from a
stored run of that scorer (`python -m src.scorer load`), never recomputed here.
"""

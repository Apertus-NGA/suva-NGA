"""The steps of the refine loop, in the order they run (priority: faithfulness, then content, then form).

1. form      code    citation forms, abbreviations, spelling, invented references, repeats
2. facts     model   every sentence backed by the ruling (F1, F2)
3. holding   model   the deciding rule and the court's answer stated (C1, C2, R1)
3b. economy  model   the outcome stated once (T4): code finds a restatement, Apertus takes it out
4. terms     model   established Swiss legal terms (T1), checked against attested terms
5. language  model   idiomatic legal German or French (T2, T3), identifiers unchanged
6. length    model   inside Suva's word band (T4), by deleting the least important sentences
7. form      code    the same code clean-up again, over whatever the model wrote
"""

from src.summarize.refine.steps.economy import Economy
from src.summarize.refine.steps.facts import Facts
from src.summarize.refine.steps.form import Form
from src.summarize.refine.steps.holding import Holding
from src.summarize.refine.steps.language import Language
from src.summarize.refine.steps.length import Length
from src.summarize.refine.steps.terms import Terms


def default_steps():
    return [Form("form"), Facts(), Holding(), Economy(), Terms(), Language(), Length(), Form("form_final")]


STEPS = default_steps()
BY_ID = {step.id: step for step in STEPS}

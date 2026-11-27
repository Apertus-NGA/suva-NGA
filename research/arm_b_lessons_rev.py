"""Second lesson worker pool: Q2 candidates in reverse order (fills the cache from the other end)."""
from arm_b_lib import *
df = load(); ex = pick_examples(); part = df[(df.q == "2026 Q2") & df.cand].iloc[::-1]
chat_many([dict(model=M70, messages=lesson_prompt(r, ex.body.tolist(), "v4"), tag="lesson_v4", max_tokens=220) for _, r in part.iterrows()], workers=4, progress=20)

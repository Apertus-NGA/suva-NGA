# Update 03 — 18:45 — interim: embeddings of raw ruling parts, agents in flight

## Status of the agents
- A (70B alone): pilot of 8 prompt variants on 50 rulings done, including thinking and 8B; full run on all 221 started 18:43.
- B (rubric filling): lesson statements being generated (40 of 221 at 18:43); question pilot done; full question run started.
- C (embeddings): BGE-M3 on subject line, reasoning chunks and core reasoning evaluated; second model and the lesson embedding still to come.
- Gateway: 1,426 Apertus calls so far, no errors seen.

## Interim scores, BGE-M3 on raw parts (held-out; baseline is 0.756 / 0.766)
| What is embedded | Best feature set alone | Best added to deterministic features |
|---|---|---|
| Subject line | 0.703 / 0.678 | 0.759 / 0.754 |
| Reasoning in chunks | 0.646 / 0.642 | 0.759 / 0.743 |
| Core reasoning | 0.647 / 0.662 | 0.675 / 0.719 (so far) |

(cross-quarter F2 / repeated-CV F2)

## Learned so far
- Embedding the raw ruling text adds nothing on top of the 11 deterministic features, and on its own is no better than submitting everything.
- Similarity to Suva's summaries from raw reasoning text is useless (same score as submitting all 221). Raw rulings and short summaries are too different in form.
- This matches the expectation that facts and boilerplate dominate raw-text embeddings. The open test is the Apertus lesson statement, which is not embedded yet.

## Next
- Wait for full runs of A and B (expected about 19:10 to 19:25).
- Combine with `arm_e_combine.py`, including recall-first thresholds.
- Iteration ends 20:00; notebook 20:00 to 20:26.

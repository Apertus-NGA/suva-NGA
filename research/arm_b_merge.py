"""Merge rubric answers (P(Ja), M70, label-first) into research/out/rubric_answers.parquet; Q2 rows only if that run finished."""
from arm_b_lib import *
parts = [pd.read_parquet(OUT / "arm_b_rubric_lab.parquet").assign(part="labelled")]
if (OUT / "arm_b_rubric_q2.parquet").exists(): parts.append(pd.read_parquet(OUT / "arm_b_rubric_q2.parquet").assign(part="2026 Q2"))
o = pd.concat(parts); o["model"] = M70; o["format"] = "label_first_p_ja"
o.to_parquet(OUT / "rubric_answers.parquet"); print(o.part.value_counts().to_dict(), "nulls", int(o[list(QUESTIONS)].isna().sum().sum()))
if len(parts) > 1: print("Q2 mean P(Ja):", o[o.part == "2026 Q2"][list(QUESTIONS)].mean().round(2).to_dict(), "\nlab mean P(Ja):", o[o.part == "labelled"][list(QUESTIONS)].mean().round(2).to_dict())

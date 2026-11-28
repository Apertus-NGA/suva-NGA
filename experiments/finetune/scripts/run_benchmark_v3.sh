#!/usr/bin/env bash
# Layer-2 benchmark of docs/FINETUNE.md §6, end to end, resumable (rerun the same command after a failure).
#
# Needs in the environment: LLM_NAME=apertus-v1-5-70b, LLM_NAME_SMALL=apertus-v1-5-8b, LLM_BASE_URL (Keera),
# LLM_API_KEY. Concurrency per model: BENCH_CONC_8B and BENCH_CONC_70B (default 4, at most 16 = the G2 team
# ceiling, passed as --slot-concurrency). Ramp of 27 Nov 22:20-22:45 CET: the 70B is throughput-bound at about
# 3.5 calls/s per key (4: 3.26, 8: 3.25, 12: 3.57, 16: 3.56 calls/s, 0 errors); the 8B ran 11.6 calls/s at 4
# and stalled at 16 (21 dropped connections, minutes without answers). So 8B 4, 70B 12.
# Cost estimate (from the audit's passes of 27 Nov, 4 workers): 45,144 calls, about 145 M prompt tokens,
# about 3.3 h (8B 3 passes ~30 min, 70B full pass ~20 min, 70B 100 repetitions on 294 rulings ~2.5 h).
# Every call goes through src/llm/ (G2); outputs and the call log stay in data/derived/finetune/bench_v3/
# (git-ignored, D-031). Only results/finetune_benchmark_v3.{md,json} (aggregates) are written outside it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"
DATA=data/derived/finetune/suva-ft-v3
MANIFEST=experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json
OUT=data/derived/finetune/bench_v3
C8="${BENCH_CONC_8B:-4}"
C70="${BENCH_CONC_70B:-4}"
RUN="uv run --frozen python -I experiments/finetune/scripts/06_benchmark_repeat.py --data-root $DATA --manifest $MANIFEST"

for v in LLM_NAME LLM_NAME_SMALL LLM_BASE_URL LLM_API_KEY; do
  if [ -z "${!v:-}" ]; then echo "missing $v (see the header of this script)"; exit 2; fi
done
[ "$LLM_NAME" = "apertus-v1-5-70b" ] || { echo "LLM_NAME must be apertus-v1-5-70b"; exit 2; }
[ "$LLM_NAME_SMALL" = "apertus-v1-5-8b" ] || { echo "LLM_NAME_SMALL must be apertus-v1-5-8b"; exit 2; }

mkdir -p "$OUT"
exec > >(tee -a "$OUT/run.log") 2>&1
echo "== $(date '+%F %T %Z') start"
python3 -I experiments/finetune/scripts/verify_dataset.py --manifest "$MANIFEST" --data "$DATA"

echo "== smoke: 3 rulings per fold, each model"
$RUN --slot-concurrency "$C8" --model apertus-v1-5-8b --subset all --reps 1 --limit 3 --out "$OUT/smoke_8b"
$RUN --slot-concurrency "$C70" --model apertus-v1-5-70b --subset all --reps 1 --limit 3 --out "$OUT/smoke_70b"

echo "== 8B zero-shot: 3 full passes"
$RUN --slot-concurrency "$C8" --model apertus-v1-5-8b --subset all --reps 3 --all --out "$OUT/8b_all"

echo "== 70B zero-shot: 1 full pass"
$RUN --slot-concurrency "$C70" --model apertus-v1-5-70b --subset all --reps 1 --all --out "$OUT/70b_all"

echo "== 70B zero-shot: 100 repetitions on positives + hard negatives (repetition ids 1..100)"
$RUN --slot-concurrency "$C70" --model apertus-v1-5-70b --subset pos_hard --reps 100 --rep-offset 1 --all --out "$OUT/70b_poshard"

echo "== report"
python3 -I experiments/finetune/scripts/07_report_v3.py --source bench --out-md results/finetune_benchmark_v3.md
echo "== $(date '+%F %T %Z') done"

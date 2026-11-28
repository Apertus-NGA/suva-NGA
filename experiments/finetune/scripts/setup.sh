#!/usr/bin/env bash
# GPU box setup (CUDA, Python 3.10+). Apertus v1.5 is gated: accept the terms on
# https://huggingface.co/swiss-ai/Apertus-v1.5-8B with your HF account, then `huggingface-cli login`.
set -euo pipefail
pip install -q "transformers[torch,vision,audio] @ git+https://github.com/swiss-ai/transformers.git@3797303dda74844e3d1f8977ff5518bb91f818b4"
pip install -q "peft>=0.13" accelerate
python -c "import torch;print(torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory/1e9,'GB')"

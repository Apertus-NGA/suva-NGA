"""Arm C: embed parts. usage: arm_c_embed.py <model_short> <part,part,...> [max_len]
Writes research/cache/emb/<model_short>__<part>.npz with ids (repeated for chunks) and L2-normalised X."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, torch
from sentence_transformers import SentenceTransformer
from arm_c_parts import parts

MODELS = {"bge-m3": "BAAI/bge-m3", "e5-instruct": "intfloat/multilingual-e5-large-instruct"}
# e5-instruct: symmetric similarity -> the documented "Instruct: ...\nQuery: " format on every text.
E5_PREFIX = "Instruct: Retrieve Swiss Federal Supreme Court rulings that decide the same legal question\nQuery: "
EMB = Path(__file__).resolve().parent / "cache" / "emb"

if __name__ == "__main__":
    short, want = sys.argv[1], sys.argv[2].split(",")
    max_len = int(sys.argv[3]) if len(sys.argv) > 3 else 512
    P = parts()
    m = SentenceTransformer(MODELS[short], device="mps")
    for part in want:
        if part not in P:
            print("missing part", part); continue
        ids, texts = P[part]
        long = part in ("facts", "reasoning", "core")
        m.max_seq_length = max_len if long else 512
        if short == "e5-instruct":
            m.max_seq_length = 512
            texts = [E5_PREFIX + t for t in texts]
        bs = 2 if m.max_seq_length > 1024 else 8
        t0 = time.time()
        X = m.encode(texts, batch_size=bs, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
        dt = time.time() - t0
        assert np.isfinite(X).all()
        np.savez(EMB / f"{short}__{part}.npz", ids=ids, X=X.astype(np.float32), max_len=m.max_seq_length, secs=dt)
        print(f"{short} {part} n={len(texts)} max_len={m.max_seq_length} {dt:.0f}s ({dt/len(texts):.2f}s/text)", flush=True)
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

"""Zero-shot baseline on Keera (base Apertus v1.5 8B / 70B) with the EXACT prompts of the dataset.
Score = P(Ja)/(P(Ja)+P(Nein)) from top_logprobs of the first output token (as in tests-keera V1).
Key: KEERA_API_KEY env var, or injected by the egress proxy. Usage:
  python3 03_keera_baseline.py --data ../data --split test --model apertus-v1-5-8b --out ../runs/keera_8b
"""
import argparse, json, math, os, ssl, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
BASE = os.environ.get("KEERA_BASE_URL", "https://gateway.keera.ch/api/v1")
CTX = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or None)


def post(payload, retries=4):
    h = {"Content-Type": "application/json"}
    if os.environ.get("KEERA_API_KEY"):
        h["x-api-key"] = os.environ["KEERA_API_KEY"]
    for k in range(retries):
        try:
            req = urllib.request.Request(BASE + "/chat/completions", json.dumps(payload).encode(), h)
            with urllib.request.urlopen(req, timeout=240, context=CTX) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            time.sleep(2 ** k * 3)
    return {"error": err}


def one(model, ex):
    d = post({"model": model, "messages": ex["prompt"], "max_tokens": 1, "temperature": 0,
              "logprobs": True, "top_logprobs": 20})
    py = pn = 0.0
    try:
        top = d["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
        for t in top:
            tok = (t.get("token") or "").strip().lower(); p = math.exp(t.get("logprob", -99))
            if tok in ("ja", "j"): py += p
            elif tok in ("nein", "nei", "ne"): pn += p
    except Exception:  # noqa: BLE001
        pass
    u = d.get("usage") or {}
    return {**ex["meta"], "label": ex["completion"][0]["content"], "p_ja": py, "p_nein": pn,
            "score": py / (py + pn) if py + pn > 0 else None, "mass": py + pn,
            "n_tokens": u.get("prompt_tokens"), "error": d.get("error")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--split", default="test")
    ap.add_argument("--model", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(a.data, f"{a.split}.jsonl"), encoding="utf-8")]
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda r: one(a.model, r), rows))
    with open(os.path.join(a.out, f"{a.split}_scores.jsonl"), "w", encoding="utf-8") as f:
        for r in res: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    import importlib.util
    spec = importlib.util.spec_from_file_location("m", os.path.join(os.path.dirname(__file__), "metrics_only.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    ok = [r for r in res if r["score"] is not None]
    mt = m.metrics(ok); mt.update({"model": a.model, "split": a.split, "n_failed": len(res) - len(ok),
                                   "elapsed_s": round(time.time() - t0),
                                   "prompt_tokens": sum(r["n_tokens"] or 0 for r in res)})
    json.dump(mt, open(os.path.join(a.out, f"{a.split}_metrics.json"), "w"), indent=2)
    print(json.dumps(mt, indent=2))

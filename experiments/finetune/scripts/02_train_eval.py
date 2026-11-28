"""LoRA fine-tuning of Apertus v1.5 8B for Suva relevance (Ja/Nein) + evaluation.

Experimental, NOT for the hack repo. Runs on one CUDA GPU with >= 40 GB (L40S 48 GB, A100, H100).
Apertus v1.5 is multimodal and needs the swiss-ai transformers fork (see setup.sh).

Design
- Prompt = the V1 Keera-test prompt (system + "Urteil <docket>: <text> ... Antworte nur mit Ja oder Nein.").
- Target = the FIRST token of the assistant answer ("Ja" / "Nein") as rendered by the chat template.
  Loss = cross-entropy on that single token (classification through the LM head, no new head).
- Score = P(Ja) / (P(Ja) + P(Nein)) at the answer position: same normalisation as the Keera logprob baseline.
- LoRA only on the text decoder's linear layers (vision/audio towers and lm_head excluded).
- Positives are oversampled (default x4) because train has ~22 positives for ~210 negatives.

Usage
  python 02_train_eval.py eval  --data ../data --split test --out runs/base            # zero-shot baseline
  python 02_train_eval.py train --data ../data --out runs/lora_r16                      # train (+ eval on valid)
  python 02_train_eval.py eval  --data ../data --split test --adapter runs/lora_r16/adapter --out runs/lora_r16
"""
import argparse, json, math, os, random, re, time

import torch
from transformers import AutoProcessor, AutoModelForMultimodalLM

MODEL_ID = os.environ.get("MODEL_ID", "swiss-ai/Apertus-v1.5-8B")
EXCLUDE = re.compile(r"(vision|visual|audio|image|encoder|projector|mm_|multi_modal|lm_head|embed)", re.I)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _as_parts(messages):
    return [{**m, "content": [{"type": "text", "text": m["content"]}]} if isinstance(m["content"], str) else m
            for m in messages]


def render(tok_or_proc, messages, add_generation_prompt):
    kw = dict(add_generation_prompt=add_generation_prompt, tokenize=True, return_dict=True)
    if os.environ.get("ENABLE_THINKING") is not None:  # Keera baseline ran non-thinking
        kw["enable_thinking"] = os.environ["ENABLE_THINKING"] == "1"
    try:  # multimodal processors usually want typed content parts
        out = tok_or_proc.apply_chat_template(_as_parts(messages), **kw)
    except Exception:  # noqa: BLE001
        out = tok_or_proc.apply_chat_template(messages, **kw)
    ids = out["input_ids"]
    return ids[0] if ids and isinstance(ids[0], list) else ids


def answer_token_ids(proc):
    """First token of the assistant answer for 'Ja' and 'Nein', found by diffing rendered templates."""
    probe = [{"role": "user", "content": "Test"}]
    base = render(proc, probe, True)
    res = {}
    for word in ("Ja", "Nein"):
        full = render(proc, probe + [{"role": "assistant", "content": word}], False)
        i = 0
        while i < len(base) and i < len(full) and base[i] == full[i]:
            i += 1
        if i != len(base):
            raise RuntimeError(f"Chat template prefix mismatch for {word!r} (prompt is not a prefix): "
                               f"diverges at {i}/{len(base)}. Inspect the template before training.")
        res[word] = full[i]
    if res["Ja"] == res["Nein"]:
        raise RuntimeError(f"Ja and Nein share their first token {res}")
    tok = getattr(proc, "tokenizer", proc)
    print("answer tokens:", {k: (v, tok.decode([v])) for k, v in res.items()})
    return res


def encode(proc, ex, max_len):
    ids = render(proc, ex["prompt"], True)
    if len(ids) > max_len:  # keep the end (question) and the head (rubrum): cut the middle
        keep_tail = 400
        ids = ids[: max_len - keep_tail] + ids[-keep_tail:]
    return ids


def load_model(adapter=None, train=False):
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16, device_map={"": 0},
                                                     attn_implementation=os.environ.get("ATTN", "sdpa"))
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
    return proc, model


@torch.no_grad()
def score(model, proc, rows, ans, max_len, out_path=None):
    model.eval()
    res = []
    t0 = time.time()
    for i, ex in enumerate(rows):
        ids = torch.tensor([encode(proc, ex, max_len)], device=model.device)
        logits = model(input_ids=ids).logits[0, -1].float()
        lp = torch.log_softmax(logits, -1)
        pj, pn = lp[ans["Ja"]].exp().item(), lp[ans["Nein"]].exp().item()
        res.append({**ex["meta"], "label": ex["completion"][0]["content"], "p_ja": pj, "p_nein": pn,
                    "score": pj / (pj + pn) if pj + pn > 0 else 0.5, "mass": pj + pn, "n_tokens": ids.shape[1]})
        if (i + 1) % 25 == 0:
            print(f"  scored {i + 1}/{len(rows)} ({time.time() - t0:.0f}s)")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for r in res:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return res


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def metrics(res):
    pos = [r["score"] for r in res if r["label"] == "Ja"]
    neg = [r["score"] for r in res if r["label"] != "Ja"]
    hard = [r["score"] for r in res if r["kind"] == "hard_negative"]
    out = {"n": len(res), "n_pos": len(pos), "auc": auc(pos, neg), "auc_vs_hard": auc(pos, hard),
           "mean_mass_ja_nein": sum(r["mass"] for r in res) / len(res)}
    for thr in (0.5, 0.1, 0.01):
        tp = sum(s >= thr for s in pos); fp = sum(s >= thr for s in neg)
        prec = tp / (tp + fp) if tp + fp else 0.0; rec = tp / len(pos) if pos else 0.0
        f2 = 5 * prec * rec / (4 * prec + rec) if prec + rec else 0.0
        out[f"thr_{thr}"] = {"recall": rec, "precision": prec, "f2": f2, "tp": tp, "fp": fp}
    # threshold giving 100 % recall: how many negatives must a lawyer read?
    if pos:
        m = min(pos)
        out["fp_at_full_recall"] = sum(s >= m for s in neg)
    return out


def train(a):
    from peft import LoraConfig, get_peft_model
    random.seed(a.seed); torch.manual_seed(a.seed)
    proc, model = load_model()
    ans = answer_token_ids(proc)
    targets = sorted({n.split(".")[-1] for n, m in model.named_modules()
                      if isinstance(m, torch.nn.Linear) and not EXCLUDE.search(n)})
    names = [n for n, m in model.named_modules() if isinstance(m, torch.nn.Linear) and not EXCLUDE.search(n)]
    print(f"LoRA targets: {targets} ({len(names)} layers)")
    cfg = LoraConfig(r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, target_modules=names, task_type="CAUSAL_LM")
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, cfg)
    model.print_trainable_parameters()

    tr = load_jsonl(os.path.join(a.data, "train.jsonl"))
    va = load_jsonl(os.path.join(a.data, "valid.jsonl"))
    tr = tr + [ex for ex in tr if ex["completion"][0]["content"] == "Ja"] * (a.oversample - 1)
    enc = [(encode(proc, ex, a.max_len), ans[ex["completion"][0]["content"]]) for ex in tr]
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    steps = math.ceil(len(enc) * a.epochs / a.grad_accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, int(0.1 * steps))) * max(0.0, (steps - s) / steps))
    os.makedirs(a.out, exist_ok=True)
    log = open(os.path.join(a.out, "train_log.jsonl"), "w")
    step, t0 = 0, time.time()
    for ep in range(a.epochs):
        random.shuffle(enc)
        model.train()
        run = 0.0
        for i, (ids, tgt) in enumerate(enc):
            x = torch.tensor([ids], device=model.device)
            logits = model(input_ids=x).logits[0, -1].float()
            loss = torch.nn.functional.cross_entropy(logits.unsqueeze(0), torch.tensor([tgt], device=x.device))
            (loss / a.grad_accum).backward()
            run += loss.item()
            if (i + 1) % a.grad_accum == 0 or i + 1 == len(enc):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
                rec = {"epoch": ep, "step": step, "loss": run / a.grad_accum, "lr": sched.get_last_lr()[0],
                       "elapsed_s": round(time.time() - t0), "max_mem_gb": torch.cuda.max_memory_allocated() / 1e9}
                print(rec); log.write(json.dumps(rec) + "\n"); log.flush(); run = 0.0
        vres = score(model, proc, va, ans, a.max_len, os.path.join(a.out, f"valid_scores_ep{ep}.jsonl"))
        vm = metrics(vres); vm["epoch"] = ep
        print("VALID", json.dumps(vm)); log.write(json.dumps({"valid": vm}) + "\n"); log.flush()
        model.save_pretrained(os.path.join(a.out, f"adapter_ep{ep}"))
    model.save_pretrained(os.path.join(a.out, "adapter"))
    json.dump(vars(a), open(os.path.join(a.out, "args.json"), "w"), indent=2)


def evaluate(a):
    proc, model = load_model(a.adapter)
    ans = answer_token_ids(proc)
    rows = load_jsonl(os.path.join(a.data, f"{a.split}.jsonl"))
    if a.limit:
        rows = rows[: a.limit]
    os.makedirs(a.out, exist_ok=True)
    res = score(model, proc, rows, ans, a.max_len, os.path.join(a.out, f"{a.split}_scores.jsonl"))
    m = metrics(res); m.update({"split": a.split, "adapter": a.adapter, "model": MODEL_ID})
    json.dump(m, open(os.path.join(a.out, f"{a.split}_metrics.json"), "w"), indent=2)
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["train", "eval"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--adapter")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--oversample", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    train(a) if a.mode == "train" else evaluate(a)

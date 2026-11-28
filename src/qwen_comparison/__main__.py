"""Same v2 writer as src/summarize, answered by the Hugging Face router.

Prints one RESULT line per fiche: critique codes, length, calls. The fiche text is not printed.
Token: HF_INFERENCE_TOKEN. Tasks JSON is the first argument. The default list sits under
tmp, in the qwen probe folder, file tasks.json (git-ignored: ruling text and tone examples, D-031).

    python -m src.qwen_comparison
    python -m src.qwen_comparison path/to/tasks100.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from src.summarize import finish
from src.summarize.prompts import qwen_comparison
from src.summarize.summarize import review, write_fiche

ROOT = Path(__file__).resolve().parents[2]
MODEL = "Qwen/Qwen3.8-27B"
URL = "https://router.huggingface.co/v1/chat/completions"
DEFAULT_TASKS = ROOT / "tmp" / "qwen_probe" / "tasks.json"


class Stop(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def main() -> None:
    token = os.environ.get("HF_INFERENCE_TOKEN")
    if not token:
        raise SystemExit("HF_INFERENCE_TOKEN is not set")
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TASKS
    tasks = json.loads(source.read_text(encoding="utf-8"))
    state = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def ask(messages: list[dict]) -> str:
        state["calls"] += 1
        payload = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": 1200,
            "temperature": 0,
            "stream": False,
            "reasoning_effort": "none",
        }
        req = urllib.request.Request(
            URL,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        data = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode()[:300]
                if exc.code in (429, 502, 503) and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise Stop(f"http {exc.code}: {detail}") from exc
        if data is None:
            raise Stop("no response")
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        state["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        state["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        if choice.get("finish_reason") == "length":
            raise Stop("generation truncated")
        text = (choice["message"].get("content") or "").strip()
        if not text:
            raise Stop("empty content")
        return text

    for task in tasks:
        state["calls"] = 0
        row = {
            "docket": task["docket"],
            "language": task["language"],
            "role": task["role"],
            "category": task["category"],
        }
        try:
            raw, _ = write_fiche(
                task["language"],
                task["target"],
                task["examples"],
                task["category"],
                ask,
                extras=qwen_comparison,
            )
            text, notes = finish.finish(
                task["language"], raw, task["target"]["text"], task["target"].get("starred")
            )
            problems = review(
                task["language"], finish.without_note(text), task["target"]["text"], task["docket"]
            )
            row.update(
                {
                    "chars": len(text),
                    "calls": state["calls"],
                    "finish_notes": notes,
                    "critiques": [item for item in problems if str(item).startswith("critique")],
                    "problems": problems,
                    "prompt_tokens": state["prompt_tokens"],
                    "completion_tokens": state["completion_tokens"],
                }
            )
        except Stop as exc:
            row.update({"error": exc.kind, "calls": state["calls"], "critiques": [], "problems": []})
        except Exception as exc:
            row.update(
                {
                    "error": type(exc).__name__,
                    "detail": str(exc)[:300],
                    "calls": state["calls"],
                    "critiques": [],
                    "problems": [],
                }
            )
        print("RESULT " + json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

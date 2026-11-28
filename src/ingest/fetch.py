"""Download the pinned Hugging Face base file, checked by SHA-256 (D-062; docs/DEPLOY.md §5).

python -m src.ingest.fetch --dest DIR     write DIR/bger.parquet; idempotent, never overwrites a good copy

A provisioning step, not a runtime one: the cluster's `fetch` job runs it once on a host with network, and an
air-gapped install copies the same file into the volume instead (the SHA-256 below is the check either way).
The revision is the one the ingest registry pins (src/ingest/registry/ingest.json, `hf_revision`); a test keeps
the two equal.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

DATASET = "voilaj/swiss-caselaw"
REVISION = "35b17aa9c3fad71011b72f78f6ab79650ec0cf96"
FILE = "data/bger.parquet"
SHA256 = "d2b2df1dedb05c62d91d834ddb6ba8084c31fae61a427fd4541a72ed35bb3711"
URL = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{FILE}"
CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(dest_dir: Path, url: str = URL, expected: str = SHA256, timeout_s: float = 60.0) -> Path:
    """DEST_DIR/bger.parquet with the expected SHA-256. Downloads to a .part file, checks, then renames."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / Path(FILE).name
    if target.is_file():
        found = sha256_of(target)
        if found == expected:
            print(f"fetch: {target} present, SHA-256 matches")
            return target
        raise SystemExit(f"fetch: {target} exists with SHA-256 {found[:12]}…, expected {expected[:12]}…: remove it")
    part = target.with_suffix(".parquet.part")
    digest = hashlib.sha256()
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(timeout_s)) as response:
        response.raise_for_status()
        with part.open("wb") as fh:
            for block in response.iter_bytes(CHUNK):
                fh.write(block)
                digest.update(block)
    if digest.hexdigest() != expected:
        part.unlink()
        raise SystemExit(f"fetch: SHA-256 {digest.hexdigest()[:12]}… does not match the pinned file: nothing kept")
    part.rename(target)
    print(f"fetch: {target} written, SHA-256 matches ({target.stat().st_size} bytes)")
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ingest.fetch", description=__doc__.splitlines()[0])
    ap.add_argument("--dest", required=True, type=Path, help="directory that receives bger.parquet")
    fetch(ap.parse_args(argv).dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

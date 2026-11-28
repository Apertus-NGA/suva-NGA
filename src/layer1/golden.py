"""Golden decisions: the certified behaviour of layer 1 and of the HF ingestion, frozen (docs/LAYER1.md §6).

`python -m src.layer1 golden --parquet PATH` reads the pinned Hugging Face file in memory (no database),
decides every ruling under every `layer1_filter` version of the registry, and compares the counts and a
SHA-256 over the canonical decisions with `expected/layer1/<version>.json`. It also checks the ingestion
(`expected/ingest/<version>.json`: rulings, counters, population manifests). Any difference fails. A change
that alters a certified decision needs a new version, never an edit of an old one (D-064).

`--write` writes the expected file of a version that has none; it never overwrites one (a certified
behaviour is immutable). Only public Hugging Face data is read: no Suva label (D-031).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from src.db.pg import ROOT, sha256_file, uuid5
from src.ingest import judgements
from src.ingest.hf_base import BaseRow, read_base
from src.ingest.models import IngestConfig
from src.layer1.engine import Decision, Layer1Engine, RuleSpec
from src.layer1.models import Layer1Config

CANONICAL = "layer1-golden-1"
LAYER1_REGISTRY = ROOT / "src" / "layer1" / "registry" / "layer1_filter.json"
INGEST_REGISTRY = ROOT / "src" / "ingest" / "registry" / "ingest.json"
EXPECTED = ROOT / "expected"


def label(version: list[int] | tuple[int, ...]) -> str:
    return "V{}.{}.{}".format(*version)


def registry_engine(version: list[int] | tuple[int, ...], registry: dict | None = None) -> Layer1Engine:
    """The engine of one `layer1_filter` version, built from the registry file (no database)."""
    reg = registry or json.loads(LAYER1_REGISTRY.read_text(encoding="utf-8"))
    ver = next(v for v in reg["versions"] if list(v["version"]) == list(version))
    rules = {r["rule_code"]: r for r in reg["rules"]}
    specs = [
        RuleSpec(code, rules[code]["definition"]["check"], rules[code]["kind"], ordinal)
        for ordinal, code in enumerate(ver["rules"], start=1)
    ]
    return Layer1Engine(Layer1Config.model_validate(ver["config"]), specs)


def canonical_line(docket: str, decision_date: str, decision: Decision) -> str:
    """One decision as a stable string: scope, reason, both decisions, rubric and every fired rule with its evidence.

    Only what the certified versions decide is included (the fired rules, not the rules evaluated without
    firing), so that the line of a ruling stays the same when traceability is added around the decision.
    """
    hits = sorted(
        [
            h.rule_code,
            h.effect,
            h.evidence.field,
            h.evidence.source,
            h.evidence.start,
            h.evidence.end,
            h.evidence.matched,
        ]
        for h in decision.hits
    )
    return json.dumps(
        {
            "docket": docket,
            "decision_date": decision_date,
            "in_suva_scope": decision.in_suva_scope,
            "reason_code": decision.reason_code,
            "score_0_100": decision.score_0_100,
            "subject": decision.subject,
            "text": decision.text,
            "rubric": decision.rubric,
            "rubric_source": decision.rubric_source,
            "hits": hits,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def ingest_summary(rows: list[BaseRow], stats: Counter) -> dict:
    """Rulings, counters and the manifest of every population, computed as load_base computes them."""
    members: dict[str, list[str]] = {}
    for r in rows:
        rid = uuid5(f"bger|{r.docket}|{r.decision_date.isoformat()}")
        for code in r.populations:
            members.setdefault(code, []).append(rid)
    populations = {
        code: {"members": len(ids), "manifest_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()}
        for code, ids in sorted(members.items())
    }
    return {"rulings": len(rows), "counters": dict(sorted(stats.items())), "populations": populations}


def layer1_summary(rows: list[BaseRow], engine: Layer1Engine) -> dict:
    lines: list[str] = []
    kept = 0
    by_reason: Counter = Counter()
    for r in sorted(rows, key=lambda x: (x.docket, x.decision_date)):
        decision = engine.decide(r.docket, {"hf_legal_area": r.legal_area}, r.gegenstand, r.text)
        lines.append(canonical_line(r.docket, r.decision_date.isoformat(), decision))
        kept += decision.kept
        by_reason[decision.reason_code] += 1
    return {
        "rulings": len(lines),
        "kept": kept,
        "dropped": len(lines) - kept,
        "by_reason": dict(sorted(by_reason.items())),
        "decisions_sha256": digest(lines),
    }


def compute(parquet: Path) -> dict[str, dict]:
    """Expected-file payloads keyed by their path relative to expected/: ingest/<v>.json, layer1/<v>.json."""
    ingest_reg = json.loads(INGEST_REGISTRY.read_text(encoding="utf-8"))
    layer1_reg = json.loads(LAYER1_REGISTRY.read_text(encoding="utf-8"))
    file_sha = sha256_file(parquet)
    out: dict[str, dict] = {}
    for ingest_ver in ingest_reg["versions"]:
        cfg = IngestConfig.model_validate(ingest_ver["config"])
        snapshot = {"hf_revision": cfg.hf_revision, "file_sha256": file_sha}
        rows, stats = read_base(parquet, cfg, judgements.export_refs())
        ingest_label = label(ingest_ver["version"])
        out[f"ingest/{ingest_label}.json"] = {
            "canonical": CANONICAL,
            "step": "ingest",
            "version": ingest_label,
            "snapshot": snapshot,
            **ingest_summary(rows, stats),
        }
        for ver in layer1_reg["versions"]:
            out[f"layer1/{label(ver['version'])}.json"] = {
                "canonical": CANONICAL,
                "step": "layer1_filter",
                "version": label(ver["version"]),
                "ingest_version": ingest_label,
                "snapshot": snapshot,
                **layer1_summary(rows, registry_engine(ver["version"], layer1_reg)),
            }
    return out


def expected_layer1(version: str, expected_dir: Path = EXPECTED) -> dict | None:
    """The certified expected file of one `layer1_filter` version, or None when the version has none yet."""
    path = expected_dir / "layer1" / f"{version}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def compare_run(
    stored: dict | None,
    *,
    population: str | None,
    snapshot_pinned: bool,
    ingest_versions: set[str],
    lines: list[str],
    kept: int,
    by_reason: dict[str, int],
) -> dict:
    """Golden status of a database run (docs/LAYER1.md §6): matched, mismatch or not_comparable (with the reason).

    A run is comparable when it decides the whole corpus, the corpus was loaded from the snapshot the expected file
    pins (same HF revision and file SHA-256) by the ingest version it names, and it holds as many rulings. Counts and
    the decisions digest are compared; the result names what differs, never a docket.
    """
    computed = {
        "rulings": len(lines),
        "kept": kept,
        "dropped": len(lines) - kept,
        "by_reason": dict(sorted(by_reason.items())),
        "decisions_sha256": digest(lines),
    }
    result = {
        "status": "not_comparable",
        "reason": "",
        "expected": None,
        "decisions_sha256": computed["decisions_sha256"],
    }
    if stored is None:
        return result | {"reason": "no expected file for this version (validate it, then golden --write)"}
    result["expected"] = f"expected/layer1/{stored['version']}.json"
    if population is not None:
        return result | {"reason": f"population {population}: the expected file certifies the whole corpus"}
    if not snapshot_pinned:
        return result | {"reason": "the corpus was not loaded from the snapshot the expected file pins"}
    if ingest_versions != {stored["ingest_version"]}:
        found = ", ".join(sorted(ingest_versions)) or "none"
        return result | {"reason": f"the corpus was loaded by ingest {found}, not {stored['ingest_version']}"}
    if len(lines) != stored["rulings"]:
        return result | {"reason": f"{len(lines)} rulings decided, the expected file certifies {stored['rulings']}"}
    differs = [key for key in computed if computed[key] != stored.get(key)]
    if differs:
        return result | {"status": "mismatch", "reason": "decisions differ from the certified ones", "differs": differs}
    return result | {"status": "matched", "reason": f"decisions equal {result['expected']}"}


def check(parquet: Path, write: bool = False, expected_dir: Path = EXPECTED) -> list[str]:
    """Compare with the expected files. Returns the problems (empty = certified behaviour unchanged)."""
    problems: list[str] = []
    for rel, payload in compute(parquet).items():
        path = expected_dir / rel
        if not path.exists():
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
            else:
                problems.append(f"{rel}: no expected file (validate the version, then --write)")
            continue
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored["snapshot"] != payload["snapshot"]:
            problems.append(f"{rel}: another input snapshot ({stored['snapshot']} != {payload['snapshot']})")
            continue
        for key in sorted(set(stored) | set(payload)):
            if stored.get(key) != payload.get(key):
                problems.append(f"{rel}: {key} differs ({stored.get(key)!r} != {payload.get(key)!r})"[:600])
    return problems

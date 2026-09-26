from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pricing_decision.offline.lake import LakeHouse

REQUIRED_DECISION = {"decision_id", "chosen_arm", "propensity"}


def ingest_decisions(lake: LakeHouse, rows: list[dict[str, Any]]) -> dict[str, int]:
    kept: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    existing = {r.get("decision_id") for r in lake.read("decisions")}
    duplicates = 0
    for row in rows:
        if not REQUIRED_DECISION.issubset(row.keys()):
            quarantined.append({**row, "reason": "schema_mismatch"})
            continue
        if row["decision_id"] in existing:
            duplicates += 1
            continue
        existing.add(row["decision_id"])
        kept.append(_strip_pii(row))
    lake.append("decisions", kept)
    if quarantined:
        lake.append("quarantine", quarantined)
    return {
        "inserted": len(kept),
        "duplicates": duplicates,
        "quarantined": len(quarantined),
        "total": len(lake.read("decisions")),
    }


def ingest_outcomes(lake: LakeHouse, rows: list[dict[str, Any]]) -> dict[str, int]:
    clean = []
    seen = {(r.get("decision_id"), r.get("event_type"), r.get("ts")) for r in lake.read("outcomes")}
    dups = 0
    for row in rows:
        if not row.get("decision_id") or not row.get("event_type"):
            continue
        key = (row.get("decision_id"), row.get("event_type"), row.get("ts"))
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        clean.append(row)
    lake.append("outcomes", clean)
    return {"inserted": len(clean), "duplicates": dups, "total": len(lake.read("outcomes"))}


def ingest_live_buffer(lake: LakeHouse, buffer_path: Path) -> dict[str, int]:
    rows = []
    if buffer_path.exists():
        with buffer_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return ingest_decisions(lake, rows)


def _strip_pii(row: dict[str, Any]) -> dict[str, Any]:
    features = dict(row.get("context_features") or {})
    for key in ("email", "phone", "name", "address"):
        features.pop(key, None)
    out = dict(row)
    out["context_features"] = features
    return out

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LakeHouse:
    """Local stand-in for Iceberg/Delta: JSONL tables with upserts by key."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.decisions_path = root / "decisions.jsonl"
        self.outcomes_path = root / "outcomes.jsonl"
        self.quarantine_path = root / "quarantine.jsonl"
        self.training_path = root / "training.jsonl"
        self.backfill_path = root / "backfill.jsonl"

    def read(self, name: str) -> list[dict[str, Any]]:
        path = self.root / f"{name}.jsonl"
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def write(self, name: str, rows: list[dict[str, Any]]) -> None:
        path = self.root / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")

    def append(self, name: str, rows: list[dict[str, Any]]) -> None:
        path = self.root / f"{name}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")

    def upsert(self, name: str, rows: list[dict[str, Any]], key: str) -> tuple[int, int]:
        existing = {r[key]: r for r in self.read(name) if r.get(key)}
        inserted = 0
        updated = 0
        for row in rows:
            kid = row.get(key)
            if not kid:
                continue
            if kid in existing:
                existing[kid] = {**existing[kid], **row}
                updated += 1
            else:
                existing[kid] = row
                inserted += 1
        self.write(name, list(existing.values()))
        return inserted, updated

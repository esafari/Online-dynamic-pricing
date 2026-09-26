from __future__ import annotations

from typing import Any

from pricing_decision.offline.ingest import ingest_outcomes
from pricing_decision.offline.lake import LakeHouse


class OutcomeService:
    """pricing.outcomes.v1 — join later on decision_id. Never blocks pricing."""

    def __init__(self, lake: LakeHouse):
        self.lake = lake

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        if not event.get("decision_id") or not event.get("event_type"):
            return {"ok": False, "reason": "decision_id and event_type required"}
        allowed = {"view", "cart", "purchase", "refund", "return"}
        if event["event_type"] not in allowed:
            return {"ok": False, "reason": "unknown_event_type"}
        stats = ingest_outcomes(self.lake, [event])
        return {"ok": True, **stats, "decision_id": event["decision_id"]}

    def for_decision(self, decision_id: str) -> list[dict[str, Any]]:
        return [r for r in self.lake.read("outcomes") if r.get("decision_id") == decision_id]

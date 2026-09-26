from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from pricing_decision.offline.ingest import ingest_decisions, ingest_outcomes
from pricing_decision.offline.lake import LakeHouse
from pricing_decision.orchestrator import PricingOrchestrator


def seed_history(orch: PricingOrchestrator, lake: LakeHouse, n: int = 120, rng: np.random.Generator | None = None) -> dict[str, Any]:
    rng = rng or np.random.default_rng(11)
    profiles = [p for p in orch.identity.public_profiles() if p.get("customer_id") or p.get("segment") == "guest"]
    skus = orch.catalog.list_skus()
    decisions: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for i in range(n):
        profile = profiles[int(rng.integers(0, len(profiles)))]
        sku = skus[int(rng.integers(0, len(skus)))]
        mode = "live" if rng.random() < 0.35 else "exploit"
        payload = {
            "customer_id": profile.get("customer_id"),
            "session_id": f"seed-{i}",
            "sku": sku["sku"],
            "cart_value": sku["list_price"],
            "channel": "web",
            "device": "mobile",
            "geo": profile.get("geo_band") or "CA",
            "mode": mode,
        }
        decision = orch.decide(payload)
        exp = dict(decision.experience)
        ts = now - timedelta(days=float(rng.uniform(2, 20)))
        exp["ts"] = ts.isoformat()
        exp["degraded"] = False
        exp["exclude_from_training"] = False
        decisions.append(exp)

        feats = exp.get("context_features") or {}
        sensitivity = float(feats.get("price_sensitivity_score") or 0.5)
        discount = float(exp.get("discount_pct") or 0) / 100.0
        price = float(exp.get("price") or sku["list_price"])
        cost = float(sku.get("cost") or 0.0)
        p_buy = float(np.clip(0.10 + 0.45 * discount * (0.4 + sensitivity) - 0.002 * price, 0.03, 0.72))
        if rng.random() < p_buy:
            revenue = price
            margin = max(price - cost, 0.0)
            outcomes.append(
                {
                    "decision_id": exp["decision_id"],
                    "event_type": "purchase",
                    "ts": (ts + timedelta(hours=float(rng.uniform(1, 48)))).isoformat(),
                    "revenue": round(revenue, 2),
                    "margin": round(margin, 2),
                    "units": 1,
                }
            )
            if rng.random() < 0.04:
                outcomes.append(
                    {
                        "decision_id": exp["decision_id"],
                        "event_type": "refund",
                        "ts": (ts + timedelta(days=4)).isoformat(),
                        "revenue": round(revenue, 2),
                        "margin": round(margin, 2),
                        "units": 1,
                    }
                )

    d_stats = ingest_decisions(lake, decisions)
    o_stats = ingest_outcomes(lake, outcomes)
    return {"decisions": d_stats, "outcomes": o_stats, "seeded": n}

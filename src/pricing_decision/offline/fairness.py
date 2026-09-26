from __future__ import annotations

from collections import defaultdict
from typing import Any

from pricing_decision.offline.lake import LakeHouse


def evaluate_fairness(lake: LakeHouse, *, max_gap: float = 0.05) -> dict[str, Any]:
    rows = [r for r in lake.read("backfill") if not r.get("censored")]
    if not rows:
        return {"ok": False, "reason": "no_rows"}

    groups: dict[str, list[float]] = defaultdict(list)
    prices: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = str(row.get("segment") or (row.get("context_features") or {}).get("segment") or "unknown")
        groups[key].append(float(row.get("reward") or 0.0))
        prices[key].append(float(row.get("price") or 0.0))

    means = {g: sum(v) / len(v) for g, v in groups.items() if v}
    price_means = {g: sum(v) / len(v) for g, v in prices.items() if v}
    if len(price_means) < 2:
        gap = 0.0
    else:
        vals = list(price_means.values())
        mid = (max(vals) + min(vals)) / 2 or 1.0
        gap = (max(vals) - min(vals)) / abs(mid)

    report = {
        "ok": True,
        "group_reward_mean": {k: round(v, 4) for k, v in means.items()},
        "group_price_mean": {k: round(v, 4) for k, v in price_means.items()},
        "price_gap": round(gap, 4),
        "threshold": max_gap,
        "fairness_ok": gap < max_gap,
        "n_per_group": {k: len(v) for k, v in groups.items()},
    }
    lake.write("fairness_report", [report])
    return report

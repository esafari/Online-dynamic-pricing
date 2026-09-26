from __future__ import annotations

from typing import Any

from pricing_decision.offline.join import compute_reward, retention_weight
from pricing_decision.offline.lake import LakeHouse


def model_reward(lake: LakeHouse, *, reward_type: str = "margin") -> dict[str, Any]:
    """Pin and (re)compute the reward definition used for this training window."""
    rows = lake.read("training") or lake.read("backfill")
    if not rows:
        return {"ok": False, "reason": "no_labeled_rows"}

    updated = []
    for row in rows:
        reward = compute_reward(row, reward_type)
        updated.append(
            {
                **row,
                "reward": round(reward, 4),
                "reward_type": reward_type,
                "retention_weight": round(retention_weight(row), 4),
            }
        )
    target = "training" if lake.read("training") else "backfill"
    lake.write(target, updated)
    if lake.read("backfill"):
        back = [{**r, "reward": next((u["reward"] for u in updated if u.get("decision_id") == r.get("decision_id")), r.get("reward")), "reward_type": reward_type} for r in lake.read("backfill")]
        lake.write("backfill", back)

    mean = sum(r["reward"] for r in updated) / len(updated)
    artifact = {
        "ok": True,
        "reward_definition": {
            "type": reward_type,
            "params": {"retention": "1 - 0.5 * churn_risk", "composite": "0.5 rev + 0.3 margin + 0.2 ltv"},
        },
        "n_rows": len(updated),
        "mean_reward": round(mean, 4),
        "nonzero_rate": round(sum(1 for r in updated if r["reward"]) / len(updated), 4),
    }
    lake.write("reward_model", [artifact])
    return artifact

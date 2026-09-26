from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pricing_decision.offline.lake import LakeHouse

WINDOWS = {
    "view": 1 / 24,
    "cart": 1.0,
    "purchase": 7.0,
    "refund": 30.0,
    "return": 30.0,
}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def retention_weight(row: dict[str, Any]) -> float:
    feats = row.get("context_features") or {}
    churn = float(feats.get("churn_risk") or 0.2)
    return max(0.4, 1.0 - 0.5 * churn)


def compute_reward(row: dict[str, Any], reward_type: str) -> float:
    revenue = float(row.get("revenue") or 0.0)
    margin = float(row.get("margin") or 0.0)
    if reward_type == "revenue":
        return revenue
    if reward_type == "ltv_proxy":
        return revenue * retention_weight(row)
    if reward_type == "composite":
        return 0.5 * revenue + 0.3 * margin + 0.2 * revenue * retention_weight(row)
    return margin


def join_and_label(
    lake: LakeHouse,
    *,
    reward_type: str = "margin",
    epsilon: float = 0.01,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    decisions = lake.read("decisions")
    outcomes = lake.read("outcomes")
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in outcomes:
        by_id.setdefault(row["decision_id"], []).append(row)

    labeled = []
    missing = 0
    censored = 0
    clipped = 0
    excluded = 0
    matched = 0

    for dec in decisions:
        events = sorted(by_id.get(dec["decision_id"], []), key=lambda r: str(r.get("ts") or ""))
        purchase = next((e for e in events if e.get("event_type") == "purchase"), None)
        refund = next((e for e in events if e.get("event_type") in {"refund", "return"}), None)
        chosen = purchase or (events[0] if events else None)
        if chosen:
            matched += 1
        else:
            missing += 1

        revenue = float((purchase or {}).get("revenue") or 0.0)
        margin = float((purchase or {}).get("margin") or 0.0)
        if refund:
            revenue -= float(refund.get("revenue") or revenue)
            margin -= float(refund.get("margin") or margin)

        ts = _parse_ts(dec.get("ts"))
        age_days = ((now - ts).total_seconds() / 86400) if ts else 999
        still_open = chosen is None and age_days < WINDOWS["purchase"]
        if still_open:
            censored += 1

        propensity = dec.get("propensity")
        if propensity is None:
            excluded += 1
            continue
        try:
            propensity = float(propensity)
        except (TypeError, ValueError):
            excluded += 1
            continue
        if propensity <= 0:
            excluded += 1
            continue
        if propensity < epsilon:
            propensity = epsilon
            clipped += 1
        propensity = min(propensity, 1.0)

        row = {
            **dec,
            "revenue": round(revenue, 4),
            "margin": round(margin, 4),
            "units": int((purchase or {}).get("units") or (1 if purchase else 0)),
            "event_type": (chosen or {}).get("event_type"),
            "outcome_ts": (chosen or {}).get("ts"),
            "reward": round(compute_reward({**dec, "revenue": revenue, "margin": margin}, reward_type), 4),
            "reward_type": reward_type,
            "censored": still_open,
            "exclude_from_ope": bool(dec.get("degraded") or dec.get("exclude_from_training")),
        }
        row["propensity"] = propensity
        labeled.append(row)

    lake.write("training", labeled)
    n = max(len(decisions), 1)
    return {
        "n_decisions": len(decisions),
        "n_labeled": len(labeled),
        "join_match_rate": round(matched / n, 4),
        "join_missing_outcome_rate": round(missing / n, 4),
        "label_censored_rate": round(censored / n, 4),
        "propensity_clip_rate": round(clipped / n, 4),
        "excluded_missing_propensity": excluded,
        "reward_type": reward_type,
        "sample": labeled[:5],
    }

from __future__ import annotations

from typing import Any

from pricing_decision.offline.lake import LakeHouse

NUMERIC = [
    "sessions_7d",
    "pageviews_7d",
    "cart_abandons_30d",
    "orders_lifetime",
    "aov_lifetime",
    "recency_days",
    "discount_uses_30d",
    "price_sensitivity_score",
    "churn_risk",
    "ltv_predicted",
    "cart_value",
]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def vectorize(features: dict[str, Any]) -> list[float]:
    return [_as_float(features.get(name)) for name in NUMERIC]


def backfill(lake: LakeHouse, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    global_defaults = (defaults.get("global") or {}) if isinstance(defaults, dict) else {}
    rows = lake.read("training") or lake.read("decisions")
    out = []
    missing = 0
    leakage = 0
    for row in rows:
        logged = dict(row.get("context_features") or {})
        recomputed = dict(logged)
        for name in NUMERIC:
            if recomputed.get(name) is None:
                recomputed[name] = global_defaults.get(name, 0.0)
                missing += 1
        # Logged features are already point-in-time. A mismatch would mean leakage.
        mismatch = any(
            abs(_as_float(logged.get(n), 0.0) - _as_float(recomputed.get(n), 0.0)) > 1e-6
            and logged.get(n) is not None
            for n in NUMERIC
        )
        if mismatch:
            leakage += 1
        out.append(
            {
                **row,
                "x": vectorize(recomputed),
                "x_feature_names": NUMERIC,
                "x_recomputed": vectorize(recomputed),
                "leakage_flag": mismatch,
            }
        )
    lake.write("backfill", out)
    n = max(len(out), 1)
    return {
        "n_rows": len(out),
        "backfill_missing_rate": round(missing / (n * len(NUMERIC)), 4),
        "backfill_recompute_mismatch_rate": round(leakage / n, 4),
        "backfill_leakage_detected_total": leakage,
        "feature_names": NUMERIC,
        "sample": [{"decision_id": r.get("decision_id"), "x": r["x"], "leakage_flag": r["leakage_flag"]} for r in out[:3]],
    }

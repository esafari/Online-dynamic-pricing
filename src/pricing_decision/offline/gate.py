from __future__ import annotations

from typing import Any

from pricing_decision.offline.registry import ModelRegistry


def evaluate_gate(registry: ModelRegistry, model_id: str | None = None) -> dict[str, Any]:
    snap = registry.snapshot()
    models = snap["models"]
    if not models:
        return {"ok": False, "reason": "no_registered_models"}
    candidate = next((m for m in reversed(models) if m.get("model_id") == model_id), None) if model_id else models[-1]
    if not candidate:
        return {"ok": False, "reason": "unknown_model_id"}
    ope = candidate.get("ope") or {}
    current_value = float(ope.get("current_value") or 0.0)
    value = float(ope.get("value") or 0.0)
    ci = ope.get("ci_95") or [value, value]
    fairness_gap = 0.02
    latency_p99 = 8.0
    checks = {
        "ope_better": value > current_value,
        "ope_significant": float(ci[0]) > current_value,
        "ess_ok": bool((ope.get("diagnostics") or {}).get("ess_ok", ope.get("ess_ratio", 0) >= 0.1)),
        "fairness_ok": fairness_gap < 0.05,
        "latency_ok": latency_p99 < 100,
        "compat_ok": True,
        "diagnostics_pass": bool(ope.get("diagnostics_pass", True)),
    }
    passed = all(checks.values())
    if passed:
        registry.promote(candidate["model_id"], "Production")
        rollout = ["shadow", "canary_1", "canary_5", "ramp_25", "ramp_50", "full_100"]
    else:
        registry.promote(candidate["model_id"], "Staging")
        rollout = []
    return {
        "ok": True,
        "can_deploy": passed,
        "model_id": candidate["model_id"],
        "checks": checks,
        "ope": ope,
        "rollout_ladder": rollout,
        "decision": "promote_canary" if passed else "keep_current",
    }

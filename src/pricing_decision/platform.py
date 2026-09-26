from __future__ import annotations

from typing import Any

from pricing_decision.architecture import system_stage
from pricing_decision.config import load_yaml
from pricing_decision.core.metrics import metrics
from pricing_decision.offline.drift import evaluate_drift
from pricing_decision.offline.fairness import evaluate_fairness
from pricing_decision.offline.pipeline import OfflinePipeline
from pricing_decision.orchestrator import PricingOrchestrator


def architecture_view() -> dict[str, Any]:
    raw = load_yaml("architecture.yaml")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "system": system_stage(),
        "layers": raw.get("layers") or [],
        "added_vs_typical_brain_diagram": raw.get("added_vs_typical_brain_diagram") or [],
        "gaps_in_original_doc": raw.get("gaps_in_original_doc") or [],
        "contracts": raw.get("contracts") or {},
        "nfrs": raw.get("nfrs") or {},
        "azure_components": load_yaml("azure_components.yaml") if isinstance(load_yaml("azure_components.yaml"), dict) else {},
        "use_cases": load_yaml("use_cases.yaml") if isinstance(load_yaml("use_cases.yaml"), list) else [],
        "segments": load_yaml("segments.yaml") if isinstance(load_yaml("segments.yaml"), dict) else {},
    }


def run_use_case(orch: PricingOrchestrator, use_case_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = load_yaml("use_cases.yaml")
    spec = next((c for c in cases if c.get("id") == use_case_id), None) if isinstance(cases, list) else None
    if not spec:
        return {"ok": False, "reason": "unknown_use_case"}
    payload = {**spec.get("defaults", {}), **(overrides or {})}
    payload.setdefault("channel", spec.get("channel", "web"))
    payload.setdefault("session_id", f"uc-{use_case_id}")
    if spec["id"] == "uc7_hybrid" and payload.get("experiment_hint") == "holdout":
        payload["mode"] = "exploit"

    if spec["id"] == "uc12_campaign":
        batch = [{**payload, **row} for row in (spec.get("batch") or [payload])]
        decisions = orch.decide_batch(batch)
        return {
            "ok": True,
            "use_case": spec,
            "batch": [
                {
                    "response": d.response.model_dump(mode="json", exclude_none=True),
                    "segment": d.context.segment,
                    "arm": d.context.bandit.chosen_arm if d.context.bandit else None,
                    "decision_id": d.response.decision_id,
                }
                for d in decisions
            ],
            "response": decisions[0].response.model_dump(mode="json", exclude_none=True) if decisions else {},
            "decision_id": decisions[0].response.decision_id if decisions else None,
        }

    restore: dict[str, Any] = {}
    if spec["id"] == "uc13_killswitch":
        restore = {"kill_switch": orch.control.kill_switch}
        orch.control.kill_switch = True
    if spec["id"] == "uc15_budget":
        restore = {"spent": orch.control.spent}
        orch.control.spent = orch.control.daily_discount_budget
    try:
        if spec["id"] == "uc14_sticky":
            first = orch.decide(payload)
            second = orch.decide({**payload, "channel": "mobile", "session_id": f"{payload['session_id']}-b"})
            return {
                "ok": True,
                "use_case": spec,
                "response": second.response.model_dump(mode="json", exclude_none=True),
                "segment": second.context.segment,
                "arm": second.context.bandit.chosen_arm if second.context.bandit else None,
                "propensity": second.context.bandit.propensity if second.context.bandit else None,
                "variant": second.context.variant,
                "degraded": second.context.degraded,
                "decision_id": second.response.decision_id,
                "sticky": {
                    "same_price": first.response.price == second.response.price,
                    "replayed": second.context.sticky_replay,
                    "first_decision_id": first.response.decision_id,
                    "second_decision_id": second.response.decision_id,
                },
            }
        decision = orch.decide(payload)
    finally:
        if "kill_switch" in restore:
            orch.control.kill_switch = restore["kill_switch"]
        if "spent" in restore:
            orch.control.spent = restore["spent"]

    return {
        "ok": True,
        "use_case": spec,
        "response": decision.response.model_dump(mode="json", exclude_none=True),
        "segment": decision.context.segment,
        "arm": decision.context.bandit.chosen_arm if decision.context.bandit else None,
        "propensity": decision.context.bandit.propensity if decision.context.bandit else None,
        "variant": decision.context.variant,
        "degraded": decision.context.degraded,
        "decision_id": decision.response.decision_id,
        "control": decision.context.control_flags,
    }


def monitor_snapshot(orch: PricingOrchestrator, offline: OfflinePipeline) -> dict[str, Any]:
    fairness = evaluate_fairness(offline.lake) if offline.lake.read("backfill") else {"ok": False, "reason": "no_backfill"}
    drift = evaluate_drift(offline.lake) if len(offline.lake.read("backfill")) >= 16 else {"ok": False, "reason": "not_enough_rows"}
    rollout = (offline.lake.read("rollout") or [None])[-1]
    return {
        "pins": orch.cache.snapshot(),
        "metrics": metrics.snapshot(),
        "lake": {
            "decisions": len(offline.lake.read("decisions")),
            "outcomes": len(offline.lake.read("outcomes")),
            "training": len(offline.lake.read("training")),
        },
        "fairness": fairness,
        "drift": drift,
        "rollout": rollout,
        "control": orch.control.snapshot(),
        "feature_skew": _feature_skew(offline),
        "nfrs": (load_yaml("architecture.yaml") or {}).get("nfrs") if isinstance(load_yaml("architecture.yaml"), dict) else {},
    }


def _feature_skew(offline: OfflinePipeline) -> dict[str, Any]:
    """Compare recent live decisions vs the training backfill (online/offline skew)."""
    live = offline.lake.read("decisions")[-40:]
    train = offline.lake.read("backfill")[-40:]
    if len(live) < 8 or len(train) < 8:
        return {"ok": False, "reason": "not_enough_rows"}
    keys = ("aov", "price_sensitivity_score", "recency_days")

    def means(rows: list[dict[str, Any]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in keys:
            vals = [float((r.get("context_features") or r).get(key) or 0) for r in rows]
            out[key] = round(sum(vals) / max(len(vals), 1), 4)
        return out

    online = means(live)
    offline_means = means(train)
    gaps = {k: round(abs(online[k] - offline_means[k]), 4) for k in keys}
    return {"ok": True, "online": online, "offline": offline_means, "abs_gap": gaps, "skew_ok": max(gaps.values()) < 2.0}


def lookup_decision(orch: PricingOrchestrator, offline: OfflinePipeline, decision_id: str) -> dict[str, Any]:
    cached = orch.idempotency_cache.get(decision_id)
    outcomes = [r for r in offline.lake.read("outcomes") if r.get("decision_id") == decision_id]
    logged = next((r for r in offline.lake.read("decisions") if r.get("decision_id") == decision_id), None)
    if not cached and not logged:
        return {"ok": False, "reason": "not_found"}
    return {
        "ok": True,
        "decision_id": decision_id,
        "cached_response": (cached or {}).get("response"),
        "experience": (cached or {}).get("experience") or logged,
        "outcomes": outcomes,
    }

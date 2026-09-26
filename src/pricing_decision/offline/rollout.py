from __future__ import annotations

from typing import Any

from pricing_decision.offline.lake import LakeHouse
from pricing_decision.offline.registry import ModelRegistry
from pricing_decision.stages.stage4_causal import SLearner
from pricing_decision.stages.stage10_cache import ModelCache

LADDER = ["shadow", "canary_1", "canary_5", "ramp_25", "ramp_50", "full_100"]
SHARE = {"shadow": 0.0, "canary_1": 0.01, "canary_5": 0.05, "ramp_25": 0.25, "ramp_50": 0.50, "full_100": 1.0}


class RegistryScorer(SLearner):
    """Serving adapter: prior S-learner plus learned τ from the registry."""

    def __init__(self, artifact: dict[str, Any], reward: str = "margin"):
        super().__init__(reward=reward)
        self.artifact = artifact
        self.tau = {k: float(v) for k, v in (artifact.get("tau") or {}).items()}
        self.model_id = artifact.get("model_id", "registry")

    def predict(self, x, arm, extras):
        mu, sigma = super().predict(x, arm, extras)
        return mu + self.tau.get(arm.id, 0.0), sigma


def advance_rollout(
    registry: ModelRegistry,
    cache: ModelCache,
    lake: LakeHouse,
    *,
    action: str = "advance",
    reward_drop: float = 0.0,
    latency_p99: float = 8.0,
    error_rate: float = 0.0,
    orch=None,
) -> dict[str, Any]:
    prod = next((m for m in reversed(registry.snapshot()["models"]) if m.get("stage") == "Production"), None)
    if not prod:
        return {"ok": False, "reason": "no_production_model"}

    state = (lake.read("rollout") or [{"stage": "shadow", "model_id": prod["model_id"]}])[-1]
    if state.get("model_id") != prod["model_id"]:
        state = {"stage": "shadow", "model_id": prod["model_id"]}

    rollback = reward_drop > 0.05 or latency_p99 > 150 or error_rate > 0.01
    if action == "rollback" or rollback:
        state = {**state, "stage": "shadow", "rolled_back": True, "reason": "kpi_regression" if rollback else "manual"}
        lake.write("rollout", [state])
        return {"ok": True, "rolled_back": True, **state, "traffic_share": 0.0}

    if action == "advance":
        idx = LADDER.index(state.get("stage", "shadow")) if state.get("stage") in LADDER else 0
        state = {"stage": LADDER[min(idx + 1, len(LADDER) - 1)], "model_id": prod["model_id"], "rolled_back": False}

    artifact = (prod.get("causal") or {})
    cache.causal = RegistryScorer(artifact, reward="margin")
    cache.cfg.versions.causal_model_id = artifact.get("model_id", cache.cfg.versions.causal_model_id)
    if orch is not None:
        orch.causal.model = cache.causal
        orch.causal._score_cache.clear()
    lake.write("rollout", [state])
    return {
        "ok": True,
        "rolled_back": False,
        "model_id": prod["model_id"],
        "stage": state["stage"],
        "traffic_share": SHARE[state["stage"]],
        "serving": "shadow_log_only" if state["stage"] == "shadow" else "canary_or_ramp",
        "pins": cache.snapshot(),
    }

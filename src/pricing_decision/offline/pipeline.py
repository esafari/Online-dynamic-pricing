from __future__ import annotations

from typing import Any

from pricing_decision.config import ROOT, get_runtime_config, load_yaml
from pricing_decision.offline.backfill import backfill
from pricing_decision.offline.bandit import update_bandit
from pricing_decision.offline.causal import train_causal
from pricing_decision.offline.drift import evaluate_drift
from pricing_decision.offline.fairness import evaluate_fairness
from pricing_decision.offline.gate import evaluate_gate
from pricing_decision.offline.ingest import ingest_live_buffer
from pricing_decision.offline.join import join_and_label
from pricing_decision.offline.lake import LakeHouse
from pricing_decision.offline.ope import evaluate_ope
from pricing_decision.offline.registry import ModelRegistry
from pricing_decision.offline.reward import model_reward
from pricing_decision.offline.rollout import advance_rollout
from pricing_decision.offline.seed import seed_history
from pricing_decision.orchestrator import PricingOrchestrator

STAGE_FLOW = ["ol_ingest", "ol_join", "ol_backfill", "ol_causal", "ol_bandit", "ol_ope", "ol_registry", "ol_gate"]


def offline_stage_catalog() -> list[dict[str, Any]]:
    docs = load_yaml("offline_stages.yaml")
    return docs if isinstance(docs, list) else []


class OfflinePipeline:
    def __init__(self, orch: PricingOrchestrator, lake: LakeHouse | None = None, registry: ModelRegistry | None = None):
        self.orch = orch
        self.lake = lake or LakeHouse(ROOT / "data" / "lake")
        self.registry = registry or ModelRegistry(ROOT / "data" / "registry")
        self.last: dict[str, Any] = {}

    def run(self, stage: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        overrides = dict(overrides or {})
        if stage == "ol_overview":
            return self.overview()
        if stage in {"ol_reward", "ol_fairness", "ol_drift", "ol_rollout"}:
            return {**self._run_one(stage, overrides), "stage": stage}

        needed = STAGE_FLOW[: STAGE_FLOW.index(stage) + 1] if stage in STAGE_FLOW else [stage]
        result: dict[str, Any] = {"stage": stage, "ok": True}
        for step in needed:
            result = {**self._run_one(step, overrides), "stage": stage, "ran": step}
            self.last[step] = result
            if result.get("ok") is False and step != stage:
                return {**result, "stage": stage, "blocked_on": step}
        return result

    def overview(self) -> dict[str, Any]:
        return {
            "stage": "ol_overview",
            "ok": True,
            "decisions": len(self.lake.read("decisions")),
            "outcomes": len(self.lake.read("outcomes")),
            "training": len(self.lake.read("training")),
            "backfill": len(self.lake.read("backfill")),
            "causal": (self.lake.read("causal_model") or [None])[0],
            "bandit": (self.lake.read("bandit_model") or [None])[0],
            "ope": (self.lake.read("ope_report") or [None])[0],
            "registry": self.registry.snapshot(),
        }

    def _run_one(self, stage: str, overrides: dict[str, Any]) -> dict[str, Any]:
        if stage == "ol_ingest":
            seeded = {}
            n = int(overrides.get("seed_n") or 0)
            if n > 0 or not self.lake.read("decisions"):
                seeded = seed_history(self.orch, self.lake, n=n or 80)
            live = {}
            if overrides.get("include_live_logs", True):
                live = ingest_live_buffer(self.lake, self.orch.cfg.settings.log_buffer_dir / "decisions.jsonl")
            return {"ok": True, "seed": seeded, "live_logs": live, "decisions": len(self.lake.read("decisions")), "outcomes": len(self.lake.read("outcomes"))}

        if stage == "ol_join":
            return {"ok": True, **join_and_label(self.lake, reward_type=str(overrides.get("reward_type") or "margin"))}

        if stage == "ol_backfill":
            features = get_runtime_config().features
            return {"ok": True, **backfill(self.lake, defaults=features.get("defaults", {}))}

        if stage == "ol_causal":
            return train_causal(
                self.lake,
                model_type=str(overrides.get("model_type") or "dr_learner"),
                min_arm_n=int(overrides.get("min_arm_n") or 5),
            )

        if stage == "ol_bandit":
            return update_bandit(self.lake, ridge=float(overrides.get("ridge") or 1.0))

        if stage == "ol_ope":
            return evaluate_ope(
                self.lake,
                estimator=str(overrides.get("estimator") or "dr"),
                candidate=str(overrides.get("candidate") or "exploit"),
            )

        if stage == "ol_registry":
            return self.registry.register(self.lake)

        if stage == "ol_gate":
            return evaluate_gate(self.registry, overrides.get("model_id"))

        if stage == "ol_reward":
            return model_reward(self.lake, reward_type=str(overrides.get("reward_type") or "margin"))

        if stage == "ol_fairness":
            return evaluate_fairness(self.lake)

        if stage == "ol_drift":
            return evaluate_drift(self.lake)

        if stage == "ol_rollout":
            return advance_rollout(
                self.registry,
                self.orch.cache,
                self.lake,
                action=str(overrides.get("action") or "advance"),
                reward_drop=float(overrides.get("reward_drop") or 0.0),
                latency_p99=float(overrides.get("latency_p99") or 8.0),
                error_rate=float(overrides.get("error_rate") or 0.0),
                orch=self.orch,
            )

        return {"ok": False, "reason": "unknown_stage"}

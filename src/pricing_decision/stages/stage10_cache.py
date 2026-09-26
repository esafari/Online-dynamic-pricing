from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from pricing_decision.config import RuntimeConfig, reload_runtime_config
from pricing_decision.stages.stage4_causal import SLearner


class ModelCache:
    """Stage 10 — in-memory assets with atomic swap and pinned in-flight versions."""

    def __init__(self, cfg: RuntimeConfig):
        self._lock = Lock()
        self.cfg = cfg
        self.causal = SLearner(reward=cfg.versions.reward_definition)
        self.guardrails = deepcopy(cfg.guardrails)
        self.ladders = deepcopy(cfg.ladders)
        self.priors = deepcopy(cfg.features.get("defaults", {}))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "causal_model_id": self.cfg.versions.causal_model_id,
                "guardrail_version": self.cfg.versions.guardrail_version,
                "candidate_set_version": self.cfg.versions.candidate_set_version,
                "policy_id": self.cfg.versions.policy_id,
            }

    def hot_reload(self) -> dict[str, Any]:
        """Atomic swap. In-flight requests keep the VersionPins already on context."""
        new_cfg = reload_runtime_config()
        new_model = SLearner(reward=new_cfg.versions.reward_definition)
        with self._lock:
            self.cfg = new_cfg
            self.causal = new_model
            self.guardrails = deepcopy(new_cfg.guardrails)
            self.ladders = deepcopy(new_cfg.ladders)
            self.priors = deepcopy(new_cfg.features.get("defaults", {}))
        return self.snapshot()

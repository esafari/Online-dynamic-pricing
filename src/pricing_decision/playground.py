from __future__ import annotations

from copy import deepcopy
from typing import Any

from pricing_decision.config import load_yaml
from pricing_decision.core.exceptions import PricingError, SkuNotFoundError, ValidationFailedError
from pricing_decision.core.models import DecisionContext
from pricing_decision.orchestrator import PricingOrchestrator
from pricing_decision.stages.stage4_causal import SLearner

STAGE_ORDER = [
    "ingestion",
    "preprocess",
    "guardrails",
    "candidates",
    "causal",
    "bandit",
    "postprocess",
    "logging",
    "response",
]


def stage_catalog() -> list[dict[str, Any]]:
    return load_yaml("stages.yaml")


class StagePlayground:
    def __init__(self, orch: PricingOrchestrator):
        self.orch = orch

    def run(self, *, stage: str, request: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        overrides = deepcopy(overrides or {})
        if stage == "cache":
            return {
                "stage": "cache",
                "ok": True,
                "pins": self.orch.cache.snapshot(),
                "reloaded": False,
            }
        if stage == "board":
            return {"stage": "board", "ok": True, **self.orch.price_board()}

        restore = self._apply_runtime_overrides(overrides)
        try:
            ctx = self.orch.ingestion.run(request)
            snapshot = self._dump(stage, ctx, reached="ingestion")
            if _stop_after(stage, "ingestion"):
                return snapshot

            ctx = self.orch.preprocess.run(ctx)
            self._apply_context_overrides(ctx, overrides)
            snapshot = self._dump(stage, ctx, reached="preprocess")
            if _stop_after(stage, "preprocess"):
                return snapshot

            ctx = self.orch.guardrails.run(ctx)
            ctx = self.orch.candidates.run(ctx)
            ctx = self.orch.fallback.ensure_arms(ctx)
            if _stop_after(stage, "guardrails"):
                return self._dump(stage, ctx, reached="guardrails")
            if _stop_after(stage, "candidates"):
                return self._dump(stage, ctx, reached="candidates")

            ctx = self.orch.causal.run(ctx)
            if _stop_after(stage, "causal"):
                return self._dump(stage, ctx, reached="causal")

            ctx = self.orch.bandit.run(ctx)
            ctx = self.orch.fallback.ensure_bandit(ctx)
            if _stop_after(stage, "bandit"):
                return self._dump(stage, ctx, reached="bandit")

            ctx = self.orch.postprocess.run(ctx)
            if _stop_after(stage, "postprocess"):
                return self._dump(stage, ctx, reached="postprocess")

            if stage == "fallback":
                ctx = self.orch.fallback.ensure_arms(ctx)
                ctx = self.orch.fallback.ensure_bandit(ctx)
                ctx = self.orch.fallback.ensure_offer(ctx)
                response = self.orch.response.run(ctx)
                experience = self.orch.logging.run(ctx)
                return self._dump(stage, ctx, reached="fallback", response=response, experience=experience)

            response = self.orch.response.run(ctx)
            experience = self.orch.logging.run(ctx)
            reached = "response" if stage == "response" else "logging"
            return self._dump(stage, ctx, reached=reached, response=response, experience=experience)
        except (ValidationFailedError, SkuNotFoundError, PricingError) as exc:
            return {
                "stage": stage,
                "ok": False,
                "error": {"reason": exc.reason, "message": exc.message, "status_code": exc.status_code},
            }
        finally:
            restore()

    def reload_cache(self) -> dict[str, Any]:
        pins = self.orch.cache.hot_reload()
        return {"stage": "cache", "ok": True, "pins": pins, "reloaded": True}

    def _apply_runtime_overrides(self, overrides: dict[str, Any]):
        orch = self.orch
        previous = {
            "fail_features": orch.feature_store.fail,
            "fail_bandit": orch.bandit.fail,
            "fail_coupon": orch.coupons.fail,
            "fail_rules": orch.guardrails.rules_available,
            "cached_rules": orch.guardrails._cached_rules,
            "fail_causal": orch.causal.timeout,
            "min_margin": orch.cfg.guardrails.get("min_margin"),
            "charm": orch.cfg.settings.charm_pricing,
            "reward": orch.causal.model.reward,
        }

        orch.feature_store.fail = bool(overrides.get("fail_features", False))
        orch.bandit.fail = bool(overrides.get("fail_bandit", False))
        orch.coupons.fail = bool(overrides.get("fail_coupon", False))
        orch.guardrails.rules_available = not bool(overrides.get("fail_rules", False))
        if overrides.get("fail_rules"):
            orch.guardrails._cached_rules = {}
        orch.causal.timeout = bool(overrides.get("fail_causal", False))
        if "min_margin" in overrides and overrides["min_margin"] is not None:
            orch.cfg.guardrails["min_margin"] = float(overrides["min_margin"])
        if "charm" in overrides:
            orch.cfg.settings.charm_pricing = bool(overrides["charm"])
        if overrides.get("reward"):
            orch.causal.model = SLearner(reward=str(overrides["reward"]))

        def restore() -> None:
            orch.feature_store.fail = previous["fail_features"]
            orch.bandit.fail = previous["fail_bandit"]
            orch.coupons.fail = previous["fail_coupon"]
            orch.guardrails.rules_available = previous["fail_rules"]
            orch.guardrails._cached_rules = previous["cached_rules"]
            orch.causal.timeout = previous["fail_causal"]
            orch.cfg.guardrails["min_margin"] = previous["min_margin"]
            orch.cfg.settings.charm_pricing = previous["charm"]
            orch.causal.model = SLearner(reward=previous["reward"])

        return restore

    def _apply_context_overrides(self, ctx: DecisionContext, overrides: dict[str, Any]) -> None:
        if not ctx.catalog:
            return
        for key in ("stock", "bot_score", "discountable", "cost", "map", "competitor_price"):
            if key in overrides and overrides[key] is not None:
                raw = overrides[key]
                ctx.catalog[key] = raw if key == "discountable" else float(raw)

        if not ctx.features:
            return
        if "consent" in overrides and overrides["consent"] is not None:
            ctx.features.consent = bool(overrides["consent"])
            if not ctx.features.consent:
                ctx.features.x_raw = self.orch.preprocess._genericize(ctx.features.x_raw, ctx)

        feature_overrides = overrides.get("features") or {}
        for key, value in feature_overrides.items():
            if value is not None:
                ctx.features.x_raw[key] = float(value)
        if "consent" in overrides or feature_overrides:
            ctx.features.x = self.orch.preprocess._encode(ctx.features.x_raw, ctx.features.missing_flags)

    def _dump(
        self,
        stage: str,
        ctx: DecisionContext,
        *,
        reached: str,
        response: Any = None,
        experience: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": stage,
            "reached": reached,
            "ok": True,
            "decision_id": ctx.decision_id,
            "trace_id": ctx.trace_id,
            "segment": ctx.segment,
            "degraded": ctx.degraded,
            "degraded_reasons": ctx.degraded_reasons,
            "timings_ms": ctx.stage_timings_ms,
            "versions": ctx.versions.model_dump(),
            "request": ctx.request.model_dump(mode="json"),
            "catalog": ctx.catalog,
            "idempotent_hit": ctx.idempotent_hit,
        }
        if ctx.features:
            payload["features"] = ctx.features.model_dump()
        if ctx.guardrails:
            payload["guardrails"] = ctx.guardrails.model_dump()
        if ctx.arms:
            payload["arms"] = [a.model_dump() for a in ctx.arms]
        if ctx.scores:
            payload["scores"] = [s.model_dump() for s in ctx.scores]
        if ctx.bandit:
            payload["bandit"] = ctx.bandit.model_dump()
        if ctx.offer:
            payload["offer"] = ctx.offer.model_dump(mode="json")
        if response is not None:
            payload["response"] = response.model_dump(mode="json", exclude_none=True)
        if experience is not None:
            payload["experience"] = experience
        return payload


def _stop_after(requested: str, current: str) -> bool:
    return requested == current

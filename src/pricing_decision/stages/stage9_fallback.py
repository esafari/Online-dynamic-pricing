from __future__ import annotations

from datetime import timedelta

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.ids import utc_now
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import Arm, BanditResult, DecisionContext, Offer


class FallbackHandler:
    """Stage 9 — always return a price, walking the fallback ladder."""

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg

    def list_price_arm(self, ctx: DecisionContext) -> Arm:
        list_price = float(ctx.catalog.get("list_price") or ctx.catalog.get("static_price") or 0.0)
        cost = float(ctx.catalog.get("cost") or 0.0)
        return Arm(
            id="disc_0",
            discount=0.0,
            price=list_price,
            margin=(list_price - cost) / list_price if list_price else None,
            list_price=list_price,
        )

    def ensure_arms(self, ctx: DecisionContext) -> DecisionContext:
        if ctx.arms:
            return ctx
        ctx.arms = [self.list_price_arm(ctx)]
        ctx.mark_degraded("no_arms")
        metrics.inc("pds_fallback_total", {"stage": "candidates", "reason": "no_arms"})
        return ctx

    def ensure_bandit(self, ctx: DecisionContext) -> DecisionContext:
        if ctx.bandit:
            return ctx
        arm = ctx.arms[0] if ctx.arms else self.list_price_arm(ctx)
        ctx.bandit = BanditResult(
            chosen_arm=arm.id,
            propensity=1.0,
            exploration_flag=False,
            bandit_version=ctx.versions.bandit_version,
        )
        ctx.mark_degraded("bandit_fallback")
        metrics.inc("pds_fallback_total", {"stage": "bandit", "reason": "bandit_fallback"})
        return ctx

    def ensure_offer(self, ctx: DecisionContext) -> DecisionContext:
        if ctx.offer:
            return ctx
        arm = ctx.chosen_arm() or self.list_price_arm(ctx)
        ctx.offer = Offer(
            price=arm.price,
            currency=ctx.catalog.get("currency", self.cfg.settings.default_currency),
            discount_pct=int(round(arm.discount * 100)),
            expires_at=utc_now() + timedelta(seconds=self.cfg.settings.offer_ttl_seconds),
            reason_codes=[f"segment:{ctx.segment}", "arm:disc_0", "fallback:list_price"],
        )
        ctx.mark_degraded("response_minimal")
        metrics.inc("pds_fallback_total", {"stage": "postprocess", "reason": "response_minimal"})
        return ctx

    def static_catalog(self, ctx: DecisionContext) -> DecisionContext:
        ctx.catalog.setdefault("list_price", 0.0)
        ctx.catalog.setdefault("currency", self.cfg.settings.default_currency)
        ctx.arms = [self.list_price_arm(ctx)]
        ctx.bandit = BanditResult(chosen_arm="disc_0", propensity=1.0, bandit_version=ctx.versions.bandit_version)
        ctx.offer = Offer(
            price=float(ctx.catalog["list_price"]),
            currency=ctx.catalog.get("currency", "USD"),
            discount_pct=0,
            expires_at=utc_now() + timedelta(seconds=self.cfg.settings.offer_ttl_seconds),
            reason_codes=["fallback:static_catalog"],
        )
        ctx.mark_degraded("static_catalog")
        metrics.inc("pds_fallback_total", {"stage": "fallback", "reason": "static_catalog"})
        metrics.inc("pds_degraded_rate")
        return ctx

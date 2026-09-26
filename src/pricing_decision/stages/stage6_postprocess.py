from __future__ import annotations

from datetime import timedelta

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.ids import utc_now
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import DecisionContext, Offer
from pricing_decision.core.tracing import stage_span
from pricing_decision.services.coupon import CouponService


class PostProcessStage:
    """Stage 6 — finalize customer-facing price, coupon, badge, expiry."""

    def __init__(self, cfg: RuntimeConfig, coupons: CouponService):
        self.cfg = cfg
        self.coupons = coupons

    def run(self, ctx: DecisionContext) -> DecisionContext:
        with stage_span(ctx, "postprocess"):
            arm = ctx.chosen_arm()
            if arm is None:
                list_price = float(ctx.catalog.get("list_price", 0.0))
                from pricing_decision.core.models import Arm

                arm = Arm(id="disc_0", discount=0.0, price=list_price, list_price=list_price)

            price = arm.price
            if self.cfg.settings.charm_pricing and arm.discount > 0:
                charming = _round_charm(price)
                floor = self._price_floor(ctx)
                if charming < floor:
                    charming = round(floor, 2)
                    metrics.inc("pds_rounding_adjustments_total")
                elif charming != price:
                    metrics.inc("pds_rounding_adjustments_total")
                price = charming

            currency = ctx.request.currency or ctx.catalog.get("currency") or self.cfg.settings.default_currency
            if currency not in {"USD", "CAD", "EUR"}:
                currency = self.cfg.settings.default_currency

            coupon = None
            if arm.discount > 0:
                coupon = self.coupons.issue(
                    ctx.unified_customer_id,
                    arm.discount,
                    self.cfg.settings.offer_ttl_seconds,
                    sku=ctx.request.sku,
                    price=round(price, 2),
                    decision_id=ctx.decision_id,
                )
                if coupon:
                    metrics.inc("pds_coupon_issue_rate")
                else:
                    ctx.mark_degraded("coupon_skip")

            badge = None
            min_badge = float(self.cfg.guardrails.get("badge_min_discount", 0.05))
            if arm.discount >= min_badge and ctx.segment != "vip":
                badge = f"{int(round(arm.discount * 100))}% off"

            expires_at = utc_now() + timedelta(seconds=self.cfg.settings.offer_ttl_seconds)
            metrics.observe("pds_expiry_ttl_histogram", self.cfg.settings.offer_ttl_seconds)

            applied = ctx.guardrails.reason_codes if ctx.guardrails else []
            reason_codes = [
                f"segment:{ctx.segment}",
                f"policy:{ctx.versions.policy_id}",
                f"arm:{arm.id}",
                f"guardrails:{','.join(applied[:4])}",
            ]
            ctx.offer = Offer(
                price=round(price, 2),
                currency=currency,
                discount_pct=int(round(arm.discount * 100)),
                badge=badge,
                coupon_code=coupon,
                expires_at=expires_at,
                reason_codes=reason_codes,
                cta="Claim your price" if arm.discount > 0 else "Continue to checkout",
            )
        return ctx

    def _price_floor(self, ctx: DecisionContext) -> float:
        cost = float(ctx.catalog.get("cost") or 0.0)
        min_margin = float(self.cfg.guardrails.get("min_margin", 0.15))
        return cost * (1.0 + min_margin)


def _round_charm(price: float) -> float:
    if price <= 0:
        return price
    dollars = int(price)
    if price == float(dollars):
        return round(dollars - 0.01, 2) if dollars > 0 else price
    return round(dollars + 0.99, 2)

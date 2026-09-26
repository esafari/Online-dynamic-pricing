from __future__ import annotations

from pricing_decision.core.models import DecisionContext, DecisionResponse
from pricing_decision.core.tracing import stage_span


class ResponseStage:
    """Stage 8 — client response. Never leak scores, propensity, or model IDs."""

    def run(self, ctx: DecisionContext) -> DecisionResponse:
        with stage_span(ctx, "response"):
            offer = ctx.offer
            if offer is None:
                return DecisionResponse(
                    price=float(ctx.catalog.get("list_price", 0.0)),
                    currency=ctx.catalog.get("currency", "USD"),
                    discount_pct=0,
                    decision_id=ctx.decision_id,
                )
            codes = offer.reason_codes[:8]
            return DecisionResponse(
                price=offer.price,
                currency=offer.currency,
                discount_pct=offer.discount_pct,
                badge=offer.badge,
                coupon_code=offer.coupon_code,
                reason_codes=codes,
                decision_id=ctx.decision_id,
                expires_at=offer.expires_at,
            )

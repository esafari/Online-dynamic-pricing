from __future__ import annotations

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import Arm, DecisionContext
from pricing_decision.core.tracing import stage_span


class CandidateStage:
    """Stage 3 — build feasible, deterministic, versioned price arms."""

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg

    def run(self, ctx: DecisionContext) -> DecisionContext:
        with stage_span(ctx, "candidates"):
            allowed = set(ctx.guardrails.allowed_arms) if ctx.guardrails else {"disc_0"}
            discounts = self._ladder(ctx)
            list_price = float(ctx.catalog.get("list_price", 0.0))
            cost = float(ctx.catalog.get("cost") or 0.0)
            msrp = float(ctx.catalog.get("msrp") or list_price)

            arms: list[Arm] = []
            seen_prices: set[float] = set()
            for discount in discounts:
                arm_id = f"disc_{int(round(discount * 100))}"
                if arm_id not in allowed:
                    continue
                price = round(list_price * (1.0 - discount), 2)
                if price > msrp + 1e-9:
                    continue
                if price in seen_prices:
                    continue
                seen_prices.add(price)
                margin = None if list_price <= 0 else (price - cost) / price if price else None
                arms.append(
                    Arm(
                        id=arm_id,
                        discount=discount,
                        price=price,
                        margin=margin,
                        list_price=list_price,
                    )
                )

            if not arms:
                ctx.mark_degraded("no_arms")
                arms = [
                    Arm(
                        id="disc_0",
                        discount=0.0,
                        price=list_price,
                        margin=(list_price - cost) / list_price if list_price else None,
                        list_price=list_price,
                    )
                ]

            max_arms = int(self.cfg.ladders.get("max_arms", 20))
            ctx.arms = arms[:max_arms]
            metrics.observe("pds_arms_generated_histogram", len(ctx.arms))
            overlap = self._overlap(ctx.arms)
            metrics.observe("pds_candidate_overlap_with_logging", overlap)
        return ctx

    def _ladder(self, ctx: DecisionContext) -> list[float]:
        ladders = self.cfg.ladders
        sku = ctx.request.sku
        if sku in ladders.get("sku_overrides", {}):
            values = list(ladders["sku_overrides"][sku])
        else:
            values = list(ladders.get("segments", {}).get(ctx.segment, ladders.get("default", [0.0])))
        # High-margin SKUs get the wider default ladder merged in.
        list_price = float(ctx.catalog.get("list_price") or 0.0)
        cost = float(ctx.catalog.get("cost") or 0.0)
        if list_price and (list_price - cost) / list_price >= 0.4:
            for d in ladders.get("default", []):
                if d not in values:
                    values.append(d)
        return sorted(set(float(v) for v in values))

    def _overlap(self, arms: list[Arm]) -> float:
        logging_arms = set(self.cfg.ladders.get("logging_policy_arms", []))
        if not logging_arms:
            return 1.0
        have = {a.discount for a in arms}
        return len(have & set(map(float, logging_arms))) / len(logging_arms)

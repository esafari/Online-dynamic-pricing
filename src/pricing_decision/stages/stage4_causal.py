from __future__ import annotations

import math
from typing import Any

import numpy as np

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import Arm, CausalScore, DecisionContext
from pricing_decision.core.tracing import stage_span


class SLearner:
    """S-learner: mu(x, a) via a compact linear model with action features.

    Coefficients are a trained-prior stand-in so the service is runnable
    without a model registry. Swap `predict` for an ONNX session in prod.
    """

    def __init__(self, reward: str = "margin"):
        self.reward = reward

    def predict(self, x: np.ndarray, arm: Arm, extras: dict[str, Any]) -> tuple[float, float]:
        sensitivity = float(extras.get("price_sensitivity_score", 0.5))
        churn = float(extras.get("churn_risk", 0.2))
        ltv = float(extras.get("ltv_predicted", 100.0))
        segment = extras.get("segment", "guest")
        list_price = float(arm.list_price or arm.price)
        cost = float(extras.get("cost", 0.0))

        # Purchase probability: higher discount helps, more so if price-sensitive.
        base_conv = 0.12 + 0.04 * (1.0 if segment == "vip" else 0.0) + 0.03 * (1.0 if segment == "at_risk" else 0.0)
        lift = arm.discount * (0.35 + 0.55 * sensitivity) - 0.08 * churn * (1.0 - arm.discount)
        p_purchase = float(np.clip(base_conv + lift, 0.02, 0.85))

        revenue = arm.price * p_purchase
        margin = max(arm.price - cost, 0.0) * p_purchase
        retention_w = 1.0 + 0.15 * math.tanh(ltv / 400.0) - 0.25 * arm.discount
        ltv_proxy = revenue * max(retention_w, 0.4)

        if self.reward == "revenue":
            mu = revenue
        elif self.reward == "ltv":
            mu = ltv_proxy
        elif self.reward == "composite":
            mu = 0.4 * revenue + 0.4 * margin + 0.2 * ltv_proxy
        else:
            mu = margin

        # Uncertainty grows for unseen / deep discounts and cold-start customers.
        cold = 0.35 if extras.get("cold_start") else 0.0
        sigma = 0.6 + 2.2 * arm.discount + cold + 0.4 * abs(sensitivity - 0.5)
        return float(mu), float(sigma)


class CausalStage:
    """Stage 4 — expected reward and uncertainty per arm."""

    def __init__(self, cfg: RuntimeConfig, model: SLearner | None = None, *, timeout: bool = False):
        self.cfg = cfg
        self.model = model or SLearner(reward=cfg.versions.reward_definition)
        self.timeout = timeout
        self._score_cache: dict[tuple[str, str, str], list[CausalScore]] = {}

    def run(self, ctx: DecisionContext) -> DecisionContext:
        with stage_span(ctx, "causal"):
            cache_key = (
                ctx.features.x_hash if ctx.features else "",
                ",".join(a.id for a in ctx.arms),
                ctx.versions.causal_model_id,
            )
            if self.timeout:
                cached = self._score_cache.get(cache_key)
                if cached:
                    ctx.scores = cached
                    ctx.mark_degraded("causal_timeout")
                    metrics.inc("pds_causal_fallback_rate")
                    return ctx
                ctx.scores = self._uniform_prior(ctx)
                ctx.mark_degraded("causal_timeout")
                metrics.inc("pds_causal_fallback_rate")
                return ctx

            extras = dict(ctx.features.x_raw) if ctx.features else {}
            extras["cost"] = ctx.catalog.get("cost", 0.0)
            extras["cold_start"] = ctx.features.missing_flags.get("orders_lifetime") if ctx.features else True
            x = np.asarray(ctx.features.x if ctx.features else [0.0], dtype=np.float64)

            scores: list[CausalScore] = []
            baseline = next((a for a in ctx.arms if a.discount == 0.0), ctx.arms[0])
            mu_base, _ = self.model.predict(x, baseline, extras)

            for arm in ctx.arms:
                mu, sigma = self.model.predict(x, arm, extras)
                p10 = mu - 1.28155 * sigma
                p90 = mu + 1.28155 * sigma
                score = CausalScore(
                    arm_id=arm.id,
                    price=arm.price,
                    mu=round(mu, 4),
                    sigma=round(sigma, 4),
                    uplift_vs_baseline=round(mu - mu_base, 4),
                    percentile_10=round(p10, 4),
                    percentile_90=round(p90, 4),
                )
                scores.append(score)
                metrics.observe("pds_causal_mu_histogram", mu, {"arm": arm.id})
                metrics.observe("pds_causal_sigma_histogram", sigma, {"arm": arm.id})

            ctx.scores = scores
            self._score_cache[cache_key] = scores
        return ctx

    def _uniform_prior(self, ctx: DecisionContext) -> list[CausalScore]:
        return [
            CausalScore(arm_id=arm.id, price=arm.price, mu=1.0, sigma=2.5, uplift_vs_baseline=0.0)
            for arm in ctx.arms
        ]

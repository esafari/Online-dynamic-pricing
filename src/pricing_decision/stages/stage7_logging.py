from __future__ import annotations

from typing import Any

from pricing_decision.core.ids import utc_now
from pricing_decision.core.models import DecisionContext
from pricing_decision.core.tracing import stage_span
from pricing_decision.services.logger import DecisionLogger


class LoggingStage:
    """Stage 7 — persist the experience tuple. Never blocks the response."""

    def __init__(self, logger: DecisionLogger):
        self.logger = logger

    def run(self, ctx: DecisionContext) -> dict[str, Any]:
        with stage_span(ctx, "logging"):
            experience = build_experience(ctx)
            ok = self.logger.emit(experience)
            if not ok:
                ctx.mark_degraded("log_buffered")
            return experience


def build_experience(ctx: DecisionContext) -> dict[str, Any]:
    offer = ctx.offer
    bandit = ctx.bandit
    features = ctx.features
    return {
        "decision_id": ctx.decision_id,
        "ts": utc_now().isoformat(),
        "customer_id": ctx.request.customer_id,
        "session_id": ctx.request.session_id,
        "trace_id": ctx.trace_id,
        "context_features": features.x_raw if features else {},
        "context_hash": features.x_hash if features else "",
        "feature_freshness": features.freshness_flags if features else {},
        "missing_flags": features.missing_flags if features else {},
        "candidate_arms": [a.id for a in ctx.arms],
        "chosen_arm": bandit.chosen_arm if bandit else "disc_0",
        "price": offer.price if offer else ctx.catalog.get("list_price"),
        "discount_pct": offer.discount_pct if offer else 0,
        "currency": offer.currency if offer else "USD",
        "propensity": bandit.propensity if bandit else 1.0,
        "exploration_flag": bandit.exploration_flag if bandit else False,
        "sampled_scores": bandit.sampled_scores if bandit else {},
        "policy_id": ctx.versions.policy_id,
        "policy_hash": ctx.versions.bandit_version,
        "causal_model_id": ctx.versions.causal_model_id,
        "candidate_set_version": ctx.versions.candidate_set_version,
        "guardrail_version": ctx.versions.guardrail_version,
        "guardrails_applied": ctx.guardrails.reason_codes if ctx.guardrails else [],
        "reason_codes": offer.reason_codes if offer else [],
        "experiment_id": ctx.experiment_id,
        "variant": ctx.variant or "treatment",
        "latency_ms": round(sum(ctx.stage_timings_ms.values()), 3),
        "degraded": ctx.degraded,
        "degraded_reasons": ctx.degraded_reasons,
        "stage_timings_ms": ctx.stage_timings_ms,
        "sku": ctx.request.sku,
        "segment": ctx.segment,
        "exclude_from_training": ctx.degraded,
        "sticky_replay": ctx.sticky_replay,
        "control_flags": ctx.control_flags,
        "action_space_version": ctx.versions.candidate_set_version,
    }

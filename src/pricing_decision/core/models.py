from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    customer_id: str | None = None
    session_id: str | None = None
    sku: str
    cart_value: float | None = None
    channel: str = "web"
    device: str = "desktop"
    geo: str = "CA"
    ts: datetime | None = None
    experiment_hint: str | None = None
    anonymous_id: str | None = None
    currency: str | None = None
    decision_id: str | None = None
    mode: str = "live"


class Arm(BaseModel):
    id: str
    discount: float
    price: float
    margin: float | None = None
    list_price: float | None = None


class CausalScore(BaseModel):
    arm_id: str
    price: float
    mu: float
    sigma: float
    uplift_vs_baseline: float = 0.0
    percentile_10: float | None = None
    percentile_90: float | None = None


class VersionPins(BaseModel):
    policy_id: str
    causal_model_id: str
    guardrail_version: str
    candidate_set_version: str
    bandit_version: str
    reward_definition: str
    response_schema_version: str


class FeatureBundle(BaseModel):
    x: list[float] = Field(default_factory=list)
    x_raw: dict[str, Any] = Field(default_factory=dict)
    x_hash: str = ""
    segment: str = "guest"
    consent: bool = False
    freshness_flags: dict[str, bool] = Field(default_factory=dict)
    missing_flags: dict[str, bool] = Field(default_factory=dict)
    degraded: bool = False


class GuardrailResult(BaseModel):
    allowed_arms: list[str] = Field(default_factory=list)
    blocked_arms: list[dict[str, str]] = Field(default_factory=list)
    constraint_vector: dict[str, Any] = Field(default_factory=dict)
    guardrail_version: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    all_blocked: bool = False
    degraded: bool = False


class BanditResult(BaseModel):
    chosen_arm: str
    propensity: float
    exploration_flag: bool = False
    sampled_scores: dict[str, float] = Field(default_factory=dict)
    bandit_version: str = ""
    tie: bool = False


class Offer(BaseModel):
    price: float
    currency: str = "USD"
    discount_pct: int = 0
    badge: str | None = None
    coupon_code: str | None = None
    expires_at: datetime | None = None
    reason_codes: list[str] = Field(default_factory=list)
    cta: str | None = None


class DecisionContext(BaseModel):
    request: DecisionRequest
    decision_id: str
    received_at: datetime
    client_ts: datetime | None = None
    trace_id: str
    span_id: str
    versions: VersionPins
    segment: str = "guest"
    unified_customer_id: str | None = None
    catalog: dict[str, Any] = Field(default_factory=dict)
    features: FeatureBundle | None = None
    guardrails: GuardrailResult | None = None
    arms: list[Arm] = Field(default_factory=list)
    scores: list[CausalScore] = Field(default_factory=list)
    bandit: BanditResult | None = None
    offer: Offer | None = None
    experiment_id: str | None = None
    variant: str | None = None
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    idempotent_hit: bool = False
    cached_response: dict[str, Any] | None = None
    sticky_replay: bool = False
    control_flags: dict[str, Any] = Field(default_factory=dict)

    def mark_degraded(self, reason: str) -> None:
        self.degraded = True
        if reason not in self.degraded_reasons:
            self.degraded_reasons.append(reason)

    def score_map(self) -> dict[str, CausalScore]:
        return {s.arm_id: s for s in self.scores}

    def arm_map(self) -> dict[str, Arm]:
        return {a.id: a for a in self.arms}

    def chosen_arm(self) -> Arm | None:
        if not self.bandit:
            return None
        return self.arm_map().get(self.bandit.chosen_arm)


class DecisionResponse(BaseModel):
    price: float
    currency: str
    discount_pct: int
    badge: str | None = None
    coupon_code: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    decision_id: str
    expires_at: datetime | None = None


class PricingDecision(BaseModel):
    response: DecisionResponse
    context: DecisionContext
    experience: dict[str, Any]

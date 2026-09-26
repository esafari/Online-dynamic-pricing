from __future__ import annotations

from typing import Any

from pricing_decision.config import RuntimeConfig, get_runtime_config, load_yaml
from pricing_decision.core.exceptions import PricingError, SkuNotFoundError, ValidationFailedError
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import BanditResult, DecisionContext, Offer, PricingDecision
from pricing_decision.services.catalog import CatalogService
from pricing_decision.services.control_plane import ControlPlane, StickyPriceStore, apply_localization
from pricing_decision.services.coupon import CouponService
from pricing_decision.services.feature_store import FeatureStore
from pricing_decision.services.gateway import ApiGateway
from pricing_decision.services.identity import IdentityService
from pricing_decision.services.logger import DecisionLogger
from pricing_decision.stages.stage0_ingestion import IngestionStage
from pricing_decision.stages.stage1_preprocess import PreprocessStage
from pricing_decision.stages.stage2_guardrails import GuardrailStage
from pricing_decision.stages.stage3_candidates import CandidateStage
from pricing_decision.stages.stage4_causal import CausalStage
from pricing_decision.stages.stage5_bandit import BanditStage
from pricing_decision.stages.stage6_postprocess import PostProcessStage
from pricing_decision.stages.stage7_logging import LoggingStage
from pricing_decision.stages.stage8_response import ResponseStage
from pricing_decision.stages.stage9_fallback import FallbackHandler
from pricing_decision.stages.stage10_cache import ModelCache


class PricingOrchestrator:
    def __init__(self, cfg: RuntimeConfig | None = None):
        self.cfg = cfg or get_runtime_config()
        self.idempotency_cache: dict[str, dict[str, Any]] = {}
        self.catalog = CatalogService(self.cfg.catalog)
        self.identity = IdentityService(self.cfg.catalog)
        self.feature_store = FeatureStore(self.cfg.catalog.get("customers", {}))
        self.coupons = CouponService()
        self.gateway = ApiGateway()
        control_cfg = load_yaml("control_plane.yaml")
        if not isinstance(control_cfg, dict):
            control_cfg = {}
        self.control = ControlPlane(control_cfg)
        self.stickiness = StickyPriceStore(ttl_seconds=int(control_cfg.get("sticky_ttl_seconds") or 1800))
        self.logger = DecisionLogger(
            self.cfg.settings.log_buffer_dir,
            kafka_enabled=self.cfg.settings.kafka_enabled,
            topic=self.cfg.settings.kafka_topic,
        )
        self.cache = ModelCache(self.cfg)
        self.ingestion = IngestionStage(self.cfg, self.catalog, self.idempotency_cache)
        self.preprocess = PreprocessStage(self.cfg, self.identity, self.feature_store)
        self.guardrails = GuardrailStage(self.cfg)
        self.candidates = CandidateStage(self.cfg)
        self.causal = CausalStage(self.cfg, model=self.cache.causal)
        self.bandit = BanditStage(self.cfg)
        self.postprocess = PostProcessStage(self.cfg, self.coupons)
        self.logging = LoggingStage(self.logger)
        self.response = ResponseStage()
        self.fallback = FallbackHandler(self.cfg)

    def decide(self, payload: dict[str, Any]) -> PricingDecision:
        payload = dict(payload)
        use_sticky = bool(payload.pop("sticky", False)) and not bool(payload.pop("ignore_sticky", False))
        ctrl = {**self.control.evaluate(payload), "sticky": use_sticky}
        if ctrl["force_exploit"]:
            payload["mode"] = "exploit"
        gate = self.gateway.admit(payload, bot_score=float(payload.get("bot_score") or 0))
        if gate["variant"] == "holdout" or gate["bot_blocked_explore"] or ctrl["force_list"]:
            payload["mode"] = "exploit"
        payload.setdefault("experiment_hint", gate["variant"])
        ctx = self.ingestion.run(payload)
        ctx.variant = gate["variant"]
        ctx.experiment_id = payload.get("experiment_hint")
        ctx.control_flags = ctrl
        if ctx.idempotent_hit and ctx.cached_response:
            cached = ctx.cached_response
            from pricing_decision.core.models import DecisionResponse

            return PricingDecision(
                response=DecisionResponse.model_validate(cached["response"]),
                context=ctx,
                experience=cached.get("experience", {}),
            )

        try:
            ctx = self._run_pipeline(ctx)
        except (ValidationFailedError, SkuNotFoundError):
            raise
        except PricingError:
            ctx = self.fallback.static_catalog(ctx)
        except Exception:
            ctx = self.fallback.static_catalog(ctx)

        ctx = self.fallback.ensure_arms(ctx)
        ctx = self.fallback.ensure_bandit(ctx)
        ctx = self.fallback.ensure_offer(ctx)
        response = self.response.run(ctx)
        experience = self.logging.run(ctx)
        result = PricingDecision(response=response, context=ctx, experience=experience)
        self.idempotency_cache[ctx.decision_id] = {
            "response": response.model_dump(mode="json"),
            "experience": experience,
        }
        if ctx.offer and not ctx.sticky_replay and ctx.control_flags.get("sticky") and ctx.variant != "holdout":
            self.stickiness.remember(
                customer_id=ctx.unified_customer_id or ctx.request.customer_id,
                sku=ctx.request.sku,
                offer=ctx.offer.model_dump(mode="json"),
                arm=ctx.bandit.chosen_arm if ctx.bandit else "disc_0",
                decision_id=ctx.decision_id,
            )
            list_price = float(ctx.catalog.get("list_price") or ctx.offer.price)
            self.control.record_spend(
                max(0.0, list_price - ctx.offer.price),
                explored=bool(ctx.bandit.exploration_flag) if ctx.bandit else False,
            )
        if ctx.degraded:
            metrics.inc("pds_degraded_rate")
        return result

    def decide_batch(self, payloads: list[dict[str, Any]]) -> list[PricingDecision]:
        return [self.decide(item) for item in payloads]

    def catalog_view(self) -> dict[str, Any]:
        return {
            "profiles": self.identity.public_profiles(),
            "skus": self.catalog.list_skus(),
        }

    def price_board(self, *, channel: str = "web", device: str = "mobile") -> dict[str, Any]:
        catalog = self.catalog_view()
        cells: list[dict[str, Any]] = []
        for profile in catalog["profiles"]:
            for sku in catalog["skus"]:
                payload = {
                    "customer_id": profile["customer_id"],
                    "session_id": f"board-{profile['customer_id'] or 'guest'}",
                    "sku": sku["sku"],
                    "cart_value": sku["list_price"],
                    "channel": channel,
                    "device": device,
                    "geo": profile.get("geo_band") or "CA",
                    "mode": "exploit",
                }
                decision = self.decide(payload)
                offer = decision.response
                features = decision.context.features
                cells.append(
                    {
                        "customer_id": profile["customer_id"],
                        "sku": sku["sku"],
                        "price": offer.price,
                        "list_price": sku["list_price"],
                        "currency": offer.currency,
                        "discount_pct": offer.discount_pct,
                        "badge": offer.badge,
                        "coupon_code": offer.coupon_code,
                        "arm": decision.context.bandit.chosen_arm if decision.context.bandit else "disc_0",
                        "segment": decision.context.segment,
                        "consent": bool(features.consent) if features else False,
                        "reason_codes": offer.reason_codes,
                        "decision_id": offer.decision_id,
                    }
                )
        return {**catalog, "cells": cells, "mode": "exploit"}

    def _run_pipeline(self, ctx: DecisionContext) -> DecisionContext:
        ctx = self.preprocess.run(ctx)
        if ctx.control_flags.get("sticky") and ctx.variant != "holdout" and not ctx.control_flags.get("force_list"):
            sticky = self.stickiness.lookup(
                ctx.unified_customer_id or ctx.request.customer_id, ctx.request.sku
            )
            if sticky:
                return self._replay_sticky(ctx, sticky)
        ctx = self.guardrails.run(ctx)
        ctx = self.candidates.run(ctx)
        if (ctx.variant or ctx.request.experiment_hint) == "holdout" or ctx.control_flags.get("force_list"):
            control = [a for a in ctx.arms if a.discount == 0.0]
            if control:
                ctx.arms = control
        ctx = self.fallback.ensure_arms(ctx)
        ctx = self.causal.run(ctx)
        ctx = self.bandit.run(ctx)
        ctx = self.fallback.ensure_bandit(ctx)
        ctx = self.postprocess.run(ctx)
        ctx = self._localize(ctx)
        return ctx

    def _replay_sticky(self, ctx: DecisionContext, sticky: dict[str, Any]) -> DecisionContext:
        ctx.sticky_replay = True
        ctx.offer = Offer.model_validate(sticky["offer"])
        ctx.bandit = BanditResult(
            chosen_arm=str(sticky.get("arm") or "disc_0"),
            propensity=1.0,
            exploration_flag=False,
            bandit_version=ctx.versions.bandit_version,
        )
        if ctx.offer.reason_codes is not None and "sticky_session" not in ctx.offer.reason_codes:
            ctx.offer.reason_codes = [*ctx.offer.reason_codes, "sticky_session"]
        ctx.control_flags = {**ctx.control_flags, "sticky_source_decision": sticky.get("decision_id")}
        return ctx

    def _localize(self, ctx: DecisionContext) -> DecisionContext:
        if not ctx.offer:
            return ctx
        catalog_ccy = str(ctx.catalog.get("currency") or self.cfg.settings.default_currency)
        price, currency, rate = apply_localization(
            ctx.offer.price,
            catalog_currency=catalog_ccy,
            request_currency=ctx.request.currency,
            fx=self.control.fx,
        )
        ctx.offer.price = price
        ctx.offer.currency = currency
        ctx.control_flags = {
            **ctx.control_flags,
            "fx_rate": rate,
            "tax_rate": self.control.tax_rate(ctx.request.geo),
        }
        return ctx

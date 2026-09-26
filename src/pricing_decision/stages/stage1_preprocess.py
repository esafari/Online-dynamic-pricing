from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import numpy as np

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.exceptions import FallbackError
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import DecisionContext, FeatureBundle
from pricing_decision.core.tracing import stage_span
from pricing_decision.services.feature_store import FeatureStore
from pricing_decision.services.identity import IdentityService

PII_KEYS = {"email", "phone", "name", "address"}


class PreprocessStage:
    """Stage 1 — identity, feature fetch, imputation, encoding, consent."""

    def __init__(self, cfg: RuntimeConfig, identity: IdentityService, features: FeatureStore):
        self.cfg = cfg
        self.identity = identity
        self.features = features
        spec = cfg.features
        self.numeric = list(spec.get("numeric", []))
        self.categorical = list(spec.get("categorical", []))
        self.defaults = spec.get("defaults", {})
        self.ttl = spec.get("ttl_seconds", {})
        self.clip = spec.get("clip", {})
        self.means = spec.get("means", {})
        self.stds = spec.get("stds", {})
        self.personalization = set(spec.get("personalization_features", []))
        self._cat_levels = self._infer_levels()

    def run(self, ctx: DecisionContext) -> DecisionContext:
        with stage_span(ctx, "preprocess"):
            profile = self.identity.resolve(
                ctx.request.customer_id,
                ctx.request.anonymous_id,
                ctx.request.geo,
            )
            ctx.unified_customer_id = profile["unified_customer_id"]
            ctx.segment = profile.get("segment", "guest")
            if profile.get("cold_start"):
                metrics.inc("pds_cold_start_rate")

            try:
                raw_features = self.features.get(ctx.unified_customer_id)
            except FallbackError:
                raw_features = {}
                ctx.mark_degraded("degraded_features")

            x_raw, freshness, missing = self._impute(ctx, profile, raw_features)
            consent = bool(profile.get("consent_personalization"))
            if ctx.request.customer_id is None and "consent_personalization" not in profile:
                consent = False
            if not profile.get("cold_start") and "consent_personalization" in profile:
                consent = bool(profile["consent_personalization"])
            if ctx.request.customer_id is None:
                # Missing customer → guest, no personalization unless explicitly granted.
                consent = bool(profile.get("consent_personalization", False))

            if not consent:
                x_raw = self._genericize(x_raw, ctx)

            x_raw = {k: v for k, v in x_raw.items() if k not in PII_KEYS}
            vector = self._encode(x_raw, missing)
            x_hash = "sha256:" + hashlib.sha256(np.asarray(vector, dtype=np.float64).tobytes()).hexdigest()

            ctx.features = FeatureBundle(
                x=vector,
                x_raw=x_raw,
                x_hash=x_hash,
                segment=ctx.segment,
                consent=consent,
                freshness_flags=freshness,
                missing_flags=missing,
                degraded="degraded_features" in ctx.degraded_reasons,
            )
            ctx.catalog["bot_score"] = profile.get("bot_score", 0.0)
            ctx.catalog["consent"] = consent
            metrics.observe("pds_feature_fetch_latency_ms", ctx.stage_timings_ms.get("preprocess", 0.0))
        return ctx

    def _impute(
        self,
        ctx: DecisionContext,
        profile: dict[str, Any],
        raw: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, bool], dict[str, bool]]:
        now = datetime.now(timezone.utc)
        updated_at = raw.pop("_updated_at", None)
        merged = {**profile.get("features", {}), **raw}
        segment = ctx.segment
        segment_defaults = self.defaults.get("segments", {}).get(segment, {})
        global_defaults = self.defaults.get("global", {})

        x_raw: dict[str, Any] = {
            "segment": segment,
            "acquisition_channel": profile.get("acquisition_channel", global_defaults.get("acquisition_channel")),
            "geo_band": profile.get("geo_band") or ctx.request.geo,
            "age_band": profile.get("age_band", global_defaults.get("age_band")),
            "channel": ctx.request.channel,
            "device": ctx.request.device,
            "cart_value": ctx.request.cart_value if ctx.request.cart_value is not None else ctx.catalog.get("list_price", 0.0),
        }
        freshness: dict[str, bool] = {}
        missing: dict[str, bool] = {}

        for name in self.numeric:
            if name == "cart_value":
                missing[name] = ctx.request.cart_value is None
                freshness[name] = True
                continue
            value = merged.get(name)
            is_missing = value is None
            is_fresh = True
            if updated_at is not None and name in self.ttl:
                age = (now - updated_at).total_seconds()
                is_fresh = age <= float(self.ttl[name])
            if is_missing or not is_fresh:
                value = segment_defaults.get(name, global_defaults.get(name, 0.0))
                if is_missing:
                    metrics.inc("pds_feature_missing_rate", {"feature": name})
                if not is_fresh:
                    metrics.inc("pds_feature_stale_rate", {"feature": name})
            lo, hi = self.clip.get(name, [None, None])
            if lo is not None and value < lo:
                value = lo
            if hi is not None and value > hi:
                value = hi
            x_raw[name] = float(value)
            missing[name] = is_missing
            freshness[name] = is_fresh and not is_missing

        return x_raw, freshness, missing

    def _genericize(self, x_raw: dict[str, Any], ctx: DecisionContext) -> dict[str, Any]:
        generic = dict(x_raw)
        global_defaults = self.defaults.get("global", {})
        for key in self.personalization:
            if key in generic:
                generic[key] = global_defaults.get(key, 0.0 if key in self.numeric else "unknown")
        generic["segment"] = ctx.segment
        return generic

    def _encode(self, x_raw: dict[str, Any], missing: dict[str, bool]) -> list[float]:
        numeric = []
        for name in self.numeric:
            raw = float(x_raw.get(name, 0.0))
            mean = float(self.means.get(name, 0.0))
            std = float(self.stds.get(name, 1.0)) or 1.0
            numeric.append((raw - mean) / std)
            numeric.append(1.0 if missing.get(name) else 0.0)

        cat = []
        for name in self.categorical:
            levels = self._cat_levels.get(name, [])
            value = str(x_raw.get(name, "unknown"))
            if value not in levels:
                levels.append(value)
                self._cat_levels[name] = levels
            one_hot = [1.0 if value == level else 0.0 for level in levels]
            cat.extend(one_hot)
        return numeric + cat

    def _infer_levels(self) -> dict[str, list[str]]:
        return {
            "segment": ["guest", "new", "returning", "vip", "at_risk"],
            "acquisition_channel": ["organic", "paid", "email", "unknown"],
            "geo_band": ["CA-ON", "CA-BC", "CA", "US", "unknown"],
            "age_band": ["18-24", "25-34", "35-44", "45-54", "unknown"],
            "channel": ["web", "app", "store"],
            "device": ["mobile", "desktop", "tablet"],
        }

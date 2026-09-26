from __future__ import annotations

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.exceptions import SkuNotFoundError, ValidationFailedError
from pricing_decision.core.ids import new_trace_ids, utc_now, uuid7
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import DecisionContext, DecisionRequest, VersionPins
from pricing_decision.core.tracing import stage_span
from pricing_decision.services.catalog import CatalogService


class IngestionStage:
    """Stage 0 — validate, pin versions, attach trace, start timers."""

    def __init__(self, cfg: RuntimeConfig, catalog: CatalogService, idempotency_cache: dict[str, dict]):
        self.cfg = cfg
        self.catalog = catalog
        self.idempotency_cache = idempotency_cache

    def run(self, payload: dict) -> DecisionContext:
        raw = dict(payload or {})
        if not raw.get("sku"):
            metrics.inc("pds_validation_errors_total", {"reason": "missing_sku"})
            raise ValidationFailedError("sku is required", reason="missing_sku")

        try:
            request = DecisionRequest.model_validate(raw)
        except Exception as exc:
            metrics.inc("pds_validation_errors_total", {"reason": "schema"})
            raise ValidationFailedError(str(exc), reason="schema") from exc

        if request.cart_value is not None and request.cart_value < 0:
            metrics.inc("pds_validation_errors_total", {"reason": "negative_cart_value"})
            raise ValidationFailedError("cart_value must be >= 0", reason="negative_cart_value")

        decision_id = request.decision_id or uuid7()
        if decision_id in self.idempotency_cache:
            cached = self.idempotency_cache[decision_id]
            ctx = self._new_context(request, decision_id)
            ctx.idempotent_hit = True
            ctx.cached_response = cached
            return ctx

        ctx = self._new_context(request, decision_id)
        with stage_span(ctx, "ingestion"):
            try:
                ctx.catalog = self.catalog.get(
                    request.sku,
                    unknown_policy=self.cfg.settings.unknown_sku_policy,
                )
            except SkuNotFoundError:
                metrics.inc("pds_validation_errors_total", {"reason": "unknown_sku"})
                raise

            if not request.customer_id:
                ctx.segment = "guest"

            metrics.inc("pds_requests_total", {"channel": request.channel, "segment": ctx.segment})
            metrics.observe("pds_version_pin_latency_ms", ctx.stage_timings_ms.get("ingestion", 0.0))
        return ctx

    def _new_context(self, request: DecisionRequest, decision_id: str) -> DecisionContext:
        received_at = utc_now()
        client_ts = request.ts
        # Clock skew: server time wins; client time is retained separately.
        if request.ts is None:
            request.ts = received_at
        elif request.ts.tzinfo is None:
            request.ts = request.ts.replace(tzinfo=received_at.tzinfo)

        trace_id, span_id = new_trace_ids()
        versions = VersionPins.model_validate(self.cfg.versions.model_dump())
        return DecisionContext(
            request=request,
            decision_id=decision_id,
            received_at=received_at,
            client_ts=client_ts,
            trace_id=trace_id,
            span_id=span_id,
            versions=versions,
            experiment_id=request.experiment_hint,
        )

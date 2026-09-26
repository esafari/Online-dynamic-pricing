from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import DecisionContext

logger = logging.getLogger("pds")


@contextmanager
def stage_span(ctx: DecisionContext, stage: str) -> Iterator[None]:
    start = time.perf_counter()
    logger.info(
        "stage_start",
        extra={"decision_id": ctx.decision_id, "trace_id": ctx.trace_id, "stage": stage},
    )
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        ctx.stage_timings_ms[stage] = round(elapsed_ms, 3)
        metrics.observe(f"pds_{stage}_latency_ms", elapsed_ms)
        logger.info(
            "stage_end",
            extra={
                "decision_id": ctx.decision_id,
                "trace_id": ctx.trace_id,
                "stage": stage,
                "latency_ms": round(elapsed_ms, 3),
            },
        )

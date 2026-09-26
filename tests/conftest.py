from __future__ import annotations

import pytest

from pricing_decision.config import get_runtime_config, get_settings
from pricing_decision.orchestrator import PricingOrchestrator


@pytest.fixture
def orch() -> PricingOrchestrator:
    get_runtime_config.cache_clear()
    get_settings.cache_clear()
    return PricingOrchestrator()


@pytest.fixture
def sample_request() -> dict:
    return {
        "customer_id": "c_91823",
        "session_id": "s_abc",
        "sku": "SKU-1234",
        "cart_value": 50.0,
        "channel": "web",
        "device": "mobile",
        "geo": "CA-ON",
        "ts": "2026-09-11T14:22:01Z",
    }

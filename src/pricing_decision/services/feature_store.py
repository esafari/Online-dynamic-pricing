from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pricing_decision.core.exceptions import FallbackError


class FeatureStore:
    """In-memory online feature store. Swap for Redis in production."""

    def __init__(self, identity_profiles: dict[str, dict[str, Any]], *, fail: bool = False):
        self._store: dict[str, dict[str, Any]] = {}
        now = datetime.now(timezone.utc)
        for cid, profile in identity_profiles.items():
            payload = deepcopy(profile.get("features", {}))
            payload["_updated_at"] = now
            self._store[cid] = payload
        self.fail = fail

    def get(self, unified_customer_id: str) -> dict[str, Any]:
        if self.fail:
            raise FallbackError("feature store unavailable", reason="degraded_features", stage="preprocess")
        return deepcopy(self._store.get(unified_customer_id, {}))

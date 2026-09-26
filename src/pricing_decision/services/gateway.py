from __future__ import annotations

from collections import defaultdict
from time import time
from typing import Any

from pricing_decision.core.exceptions import ValidationFailedError


class ApiGateway:
    """Edge checks: rate limit, bot screen, experiment assignment."""

    def __init__(self, *, rps: int = 50, bot_max: float = 0.8):
        self.rps = rps
        self.bot_max = bot_max
        self._hits: dict[str, list[float]] = defaultdict(list)

    def admit(self, payload: dict[str, Any], *, bot_score: float = 0.0) -> dict[str, Any]:
        key = str(payload.get("customer_id") or payload.get("session_id") or "anon")
        now = time()
        window = [t for t in self._hits[key] if now - t < 1.0]
        window.append(now)
        self._hits[key] = window
        if len(window) > self.rps:
            raise ValidationFailedError("rate limit exceeded", reason="rate_limited")
        if bot_score >= self.bot_max:
            return {
                "allowed": True,
                "bot_blocked_explore": True,
                "variant": "exploit",
                "reason": "bot_score",
            }
        hint = payload.get("experiment_hint")
        variant = hint if hint in {"holdout", "bandit", "shadow", "treatment"} else "bandit"
        return {"allowed": True, "bot_blocked_explore": False, "variant": variant, "reason": "ok"}

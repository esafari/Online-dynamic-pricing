from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


class CouponService:
    """Issues redeemable offers and keeps a ledger so policy changes cannot void them."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.issued: list[str] = []
        self.ledger: dict[str, dict[str, Any]] = {}

    def issue(
        self,
        customer_id: str | None,
        discount: float,
        ttl: int = 600,
        *,
        sku: str | None = None,
        price: float | None = None,
        decision_id: str | None = None,
    ) -> str | None:
        if self.fail:
            return None
        if discount <= 0:
            return None
        token = secrets.token_hex(3).upper()
        pct = int(round(discount * 100))
        seed = hashlib.sha256(f"{customer_id}:{pct}:{ttl}".encode()).hexdigest()[:4].upper()
        code = f"SAVE{pct}-{token}{seed}"
        self.issued.append(code)
        self.ledger[code] = {
            "code": code,
            "customer_id": customer_id,
            "sku": sku,
            "price": price,
            "discount": discount,
            "decision_id": decision_id,
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(),
            "redeemed": False,
            "honored_after_policy_change": True,
        }
        return code

    def lookup(self, code: str) -> dict[str, Any] | None:
        rec = self.ledger.get(code)
        if not rec:
            return None
        return dict(rec)

    def redeem(self, code: str) -> dict[str, Any]:
        rec = self.ledger.get(code)
        if not rec:
            return {"ok": False, "reason": "unknown_offer"}
        if rec.get("redeemed"):
            return {"ok": False, "reason": "already_redeemed", "offer": rec}
        rec["redeemed"] = True
        rec["redeemed_at"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "offer": rec}

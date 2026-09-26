from __future__ import annotations

from copy import deepcopy
from typing import Any


class IdentityService:
    def __init__(self, catalog: dict[str, Any]):
        self._customers: dict[str, dict[str, Any]] = deepcopy(catalog.get("customers", {}))

    def resolve(
        self,
        customer_id: str | None,
        anonymous_id: str | None = None,
        geo: str | None = None,
    ) -> dict[str, Any]:
        if customer_id and customer_id in self._customers:
            profile = deepcopy(self._customers[customer_id])
            profile["cold_start"] = not bool(profile.get("features"))
            return profile

        guest_id = customer_id or anonymous_id or "guest"
        return {
            "unified_customer_id": guest_id,
            "display_name": "Guest shopper" if not customer_id else guest_id,
            "persona": "Anonymous" if not customer_id else "New / cold start",
            "segment": "guest" if not customer_id else "new",
            "acquisition_channel": "unknown",
            "geo_band": geo or "CA",
            "age_band": "unknown",
            "consent_personalization": False if not customer_id else True,
            "bot_score": 0.15,
            "features": {},
            "cold_start": True,
        }

    def public_profiles(self) -> list[dict[str, Any]]:
        rows = []
        for cid, raw in self._customers.items():
            if raw.get("hidden"):
                continue
            features = raw.get("features") or {}
            rows.append(
                {
                    "customer_id": cid,
                    "display_name": raw.get("display_name", cid),
                    "persona": raw.get("persona", raw.get("segment", "guest")),
                    "headline": raw.get("headline", ""),
                    "segment": raw.get("segment", "guest"),
                    "acquisition_channel": raw.get("acquisition_channel"),
                    "geo_band": raw.get("geo_band"),
                    "age_band": raw.get("age_band"),
                    "consent_personalization": bool(raw.get("consent_personalization")),
                    "cold_start": not bool(features),
                    "features": features,
                }
            )
        rows.append(
            {
                "customer_id": None,
                "display_name": "Guest shopper",
                "persona": "Anonymous",
                "headline": "No account — guest segment, no personalization",
                "segment": "guest",
                "acquisition_channel": "unknown",
                "geo_band": "CA",
                "age_band": "unknown",
                "consent_personalization": False,
                "cold_start": True,
                "features": {},
            }
        )
        return rows

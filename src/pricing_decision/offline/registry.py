from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pricing_decision.offline.lake import LakeHouse


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / "models.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"models": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def register(self, lake: LakeHouse) -> dict[str, Any]:
        causal = (lake.read("causal_model") or [None])[0]
        bandit = (lake.read("bandit_model") or [None])[0]
        ope = (lake.read("ope_report") or [None])[0]
        if not causal:
            return {"ok": False, "reason": "missing_causal_artifact"}
        data = self._load()
        model_id = causal.get("model_id")
        if any(m.get("model_id") == model_id and m.get("stage") != "Archived" for m in data["models"]):
            # allow a new run to create a versioned copy
            model_id = f"{model_id}_{len(data['models']) + 1}"
            causal = {**causal, "model_id": model_id}
        record = {
            "model_id": model_id,
            "type": causal.get("type"),
            "stage": "Staging",
            "causal": causal,
            "bandit": bandit,
            "ope": ope,
            "lineage": {
                "n_samples": causal.get("n_samples"),
                "reward_metrics": causal.get("metrics"),
                "data_hash": causal.get("trained_on"),
            },
        }
        data["models"].append(record)
        self._save(data)
        return {"ok": True, "registered": record, "models_total": len(data["models"])}

    def promote(self, model_id: str, stage: str) -> dict[str, Any]:
        data = self._load()
        for model in data["models"]:
            if model.get("model_id") == model_id:
                if not model.get("lineage"):
                    return {"ok": False, "reason": "missing_lineage"}
                model["stage"] = stage
                self._save(data)
                return {"ok": True, "model": model}
        return {"ok": False, "reason": "unknown_model_id"}

    def snapshot(self) -> dict[str, Any]:
        data = self._load()
        counts: dict[str, int] = {}
        for model in data["models"]:
            counts[model.get("stage", "None")] = counts.get(model.get("stage", "None"), 0) + 1
        return {"models": data["models"], "counts": counts}

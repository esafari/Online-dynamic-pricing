from __future__ import annotations

from typing import Any

import numpy as np

from pricing_decision.offline.backfill import NUMERIC
from pricing_decision.offline.lake import LakeHouse


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 8) -> float:
    if len(expected) < 8 or len(actual) < 8:
        return 0.0
    lo = min(float(expected.min()), float(actual.min()))
    hi = max(float(expected.max()), float(actual.max()))
    if hi <= lo:
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    e, _ = np.histogram(expected, bins=edges)
    a, _ = np.histogram(actual, bins=edges)
    e = np.clip(e / max(e.sum(), 1), 1e-4, 1)
    a = np.clip(a / max(a.sum(), 1), 1e-4, 1)
    return float(np.sum((a - e) * np.log(a / e)))


def evaluate_drift(lake: LakeHouse, *, psi_limit: float = 0.2) -> dict[str, Any]:
    rows = [r for r in lake.read("backfill") if r.get("x")]
    if len(rows) < 16:
        return {"ok": False, "reason": "not_enough_rows_for_psi"}
    mid = len(rows) // 2
    older, newer = rows[:mid], rows[mid:]
    per_feature = {}
    for i, name in enumerate(NUMERIC):
        exp = np.asarray([r["x"][i] for r in older], dtype=float)
        act = np.asarray([r["x"][i] for r in newer], dtype=float)
        per_feature[name] = round(_psi(exp, act), 4)
    p_old = np.asarray([float(r["propensity"]) for r in older], dtype=float)
    p_new = np.asarray([float(r["propensity"]) for r in newer], dtype=float)
    psi_p = round(_psi(p_old, p_new), 4)
    max_psi = max(list(per_feature.values()) + [psi_p])
    report = {
        "ok": True,
        "psi_by_feature": per_feature,
        "psi_propensity": psi_p,
        "max_psi": max_psi,
        "threshold": psi_limit,
        "drift_ok": max_psi < psi_limit,
    }
    lake.write("drift_report", [report])
    return report

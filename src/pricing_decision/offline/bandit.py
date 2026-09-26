from __future__ import annotations

from typing import Any

import numpy as np

from pricing_decision.offline.lake import LakeHouse


def update_bandit(lake: LakeHouse, *, ridge: float = 1.0, decay: float = 1.0) -> dict[str, Any]:
    rows = [r for r in lake.read("backfill") if r.get("x") and not r.get("censored") and not r.get("exclude_from_training")]
    if not rows:
        return {"ok": False, "reason": "no_training_rows"}

    dim = len(rows[0]["x"])
    arms = sorted({str(r["chosen_arm"]) for r in rows})
    A_inv: dict[str, list[list[float]]] = {}
    theta: dict[str, list[float]] = {}
    ess: dict[str, float] = {}

    for arm in arms:
        subset = [r for r in rows if r["chosen_arm"] == arm]
        if not subset:
            A = ridge * np.eye(dim)
            A_inv[arm] = np.linalg.inv(A).tolist()
            theta[arm] = np.zeros(dim).tolist()
            ess[arm] = 0.0
            continue
        x = np.asarray([r["x"] for r in subset], dtype=float)
        y = np.asarray([float(r.get("reward") or 0.0) for r in subset], dtype=float)
        p = np.clip(np.asarray([float(r["propensity"]) for r in subset], dtype=float), 0.01, 1.0)
        w = (1.0 / p) * (decay ** np.arange(len(subset))[::-1])
        a_mat = x.T @ (w[:, None] * x) + ridge * np.eye(dim)
        b_vec = x.T @ (w * y)
        inv = np.linalg.pinv(a_mat)
        A_inv[arm] = inv.tolist()
        theta[arm] = (inv @ b_vec).tolist()
        ess[arm] = round(float((w.sum() ** 2) / ((w**2).sum() or 1.0)), 2)

    artifact = {
        "bandit_id": "ts_v8",
        "arms": arms,
        "theta_hat": {k: [round(v, 5) for v in vec] for k, vec in theta.items()},
        "theta_norm": {k: round(float(np.linalg.norm(vec)), 4) for k, vec in theta.items()},
        "effective_sample_size": ess,
        "n_updates": len(rows),
        "ridge": ridge,
    }
    lake.write("bandit_model", [artifact])
    return {"ok": True, **artifact, "A_inv_stored": True}

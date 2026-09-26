from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from pricing_decision.offline.lake import LakeHouse

ARM_ORDER = ["disc_0", "disc_5", "disc_10", "disc_15", "disc_20", "disc_25", "disc_30"]


def _ridge(x: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    d = x.shape[1]
    gram = x.T @ x + l2 * np.eye(d)
    return np.linalg.solve(gram, x.T @ y)


def _one_hot(arms: list[str], vocab: list[str]) -> np.ndarray:
    idx = {a: i for i, a in enumerate(vocab)}
    out = np.zeros((len(arms), len(vocab)))
    for n, arm in enumerate(arms):
        if arm in idx:
            out[n, idx[arm]] = 1.0
    return out


def _usable(rows: list[dict[str, Any]], min_arm_n: int) -> tuple[list[dict[str, Any]], list[str]]:
    counts = Counter(r.get("chosen_arm") for r in rows if not r.get("censored") and not r.get("exclude_from_training"))
    keep_arms = [a for a, n in counts.items() if a and n >= min_arm_n]
    keep_arms = [a for a in ARM_ORDER if a in keep_arms] or list(keep_arms)
    usable = [
        r
        for r in rows
        if r.get("chosen_arm") in keep_arms
        and not r.get("censored")
        and not r.get("exclude_from_training")
        and r.get("x")
    ]
    return usable, keep_arms


def train_causal(
    lake: LakeHouse,
    *,
    model_type: str = "dr_learner",
    min_arm_n: int = 8,
    l2: float = 1.0,
) -> dict[str, Any]:
    rows = lake.read("backfill")
    usable, arms = _usable(rows, min_arm_n)
    if len(usable) < 20 or len(arms) < 2:
        return {"ok": False, "reason": "not_enough_data", "n_samples": len(usable), "arms": arms}

    x = np.asarray([r["x"] for r in usable], dtype=float)
    y = np.asarray([float(r.get("reward") or 0.0) for r in usable], dtype=float)
    a = [str(r["chosen_arm"]) for r in usable]
    p = np.asarray([float(r["propensity"]) for r in usable], dtype=float)
    oh = _one_hot(a, arms)
    xa = np.hstack([x, oh])

    # Cross-fit nuisance models (2 folds keep the demo snappy).
    n = len(usable)
    fold = np.arange(n) % 2
    mu_hat = np.zeros(n)
    for k in (0, 1):
        train = fold != k
        val = fold == k
        if train.sum() < 5 or val.sum() < 1:
            continue
        beta = _ridge(xa[train], y[train], l2)
        mu_hat[val] = xa[val] @ beta
    global_beta = _ridge(xa, y, l2)

    def predict_mu(x_row: np.ndarray, arm: str) -> float:
        vec = np.concatenate([x_row, _one_hot([arm], arms)[0]])
        return float(vec @ global_beta)

    tau: dict[str, float] = {}
    baseline = "disc_0" if "disc_0" in arms else arms[0]
    if model_type == "dr_learner":
        e = np.clip(p, 0.01, 1.0)
        correction = (y - mu_hat) / e
        for arm in arms:
            mu_t = np.array([predict_mu(x[i], arm) for i in range(n)])
            mu_b = np.array([predict_mu(x[i], baseline) for i in range(n)])
            pseudo = mu_t - mu_b + correction
            tau_beta = _ridge(x, pseudo, l2)
            tau[arm] = float(np.mean(x @ tau_beta))
    else:
        for arm in arms:
            mu_t = np.mean([predict_mu(x[i], arm) for i in range(n)])
            mu_b = np.mean([predict_mu(x[i], baseline) for i in range(n)])
            tau[arm] = float(mu_t - mu_b)

    y_hat = xa @ global_beta
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    artifact = {
        "model_id": "dr_v3" if model_type == "dr_learner" else "s_learner_v2",
        "type": model_type,
        "arms": arms,
        "beta": global_beta.tolist(),
        "feature_dim": int(x.shape[1]),
        "metrics": {
            "r2_reward": round(1.0 - ss_res / ss_tot, 4),
            "dr_loss_val": round(float(np.mean((y - mu_hat) ** 2)), 4),
            "tau_mean": round(float(np.mean(list(tau.values()))), 4),
        },
        "tau": {k: round(v, 4) for k, v in tau.items()},
        "n_samples": n,
        "n_samples_per_arm": dict(Counter(a)),
        "trained_on": f"{len(usable)} labeled rows",
    }
    lake.write("causal_model", [artifact])
    return {"ok": True, **artifact}

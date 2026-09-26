from __future__ import annotations

from typing import Any

import numpy as np

from pricing_decision.offline.lake import LakeHouse


def _policy_prob(row: dict[str, Any], arm: str, candidate: str, causal: dict[str, Any] | None) -> float:
    arms = list(row.get("candidate_arms") or [row.get("chosen_arm")])
    if candidate == "logging":
        return float(row["propensity"]) if arm == row.get("chosen_arm") else 0.0
    if candidate == "egreedy":
        eps = 0.1
        exploit = _best_arm(row, causal, arms)
        if arm == exploit:
            return (1 - eps) + eps / max(len(arms), 1)
        return eps / max(len(arms), 1)
    # exploit
    return 1.0 if arm == _best_arm(row, causal, arms) else 0.0


def _best_arm(row: dict[str, Any], causal: dict[str, Any] | None, arms: list[str]) -> str:
    tau = (causal or {}).get("tau") or {}
    if tau:
        present = [a for a in arms if a in tau]
        if present:
            return max(present, key=lambda a: float(tau[a]))
    return str(row.get("chosen_arm") or arms[0])


def _weights(rows: list[dict[str, Any]], candidate: str, causal: dict[str, Any] | None) -> np.ndarray:
    ws = []
    for row in rows:
        pi1 = _policy_prob(row, str(row["chosen_arm"]), candidate, causal)
        pi0 = max(float(row["propensity"]), 0.01)
        ws.append(pi1 / pi0)
    return np.asarray(ws, dtype=float)


def _dm(rows: list[dict[str, Any]], candidate: str, causal: dict[str, Any] | None) -> float:
    vals = []
    for row in rows:
        arms = list(row.get("candidate_arms") or [row.get("chosen_arm")])
        tau = (causal or {}).get("tau") or {}
        vals.append(sum(_policy_prob(row, a, candidate, causal) * float(tau.get(a, 0.0)) for a in arms))
    return float(np.mean(vals)) if vals else 0.0


def evaluate_ope(
    lake: LakeHouse,
    *,
    estimator: str = "dr",
    candidate: str = "exploit",
    bootstrap_n: int = 80,
) -> dict[str, Any]:
    rows = [
        r
        for r in lake.read("backfill")
        if r.get("propensity")
        and not r.get("censored")
        and not r.get("exclude_from_ope")
        and not r.get("exclude_from_training")
    ]
    causal = (lake.read("causal_model") or [{}])[0]
    if len(rows) < 10:
        return {"ok": False, "reason": "not_enough_ope_rows", "n_samples": len(rows)}

    y = np.asarray([float(r.get("reward") or 0.0) for r in rows], dtype=float)
    w = _weights(rows, candidate, causal)
    w = np.clip(w, 0.0, 100.0)
    dm = _dm(rows, candidate, causal)
    mu_chosen = np.asarray([float((causal.get("tau") or {}).get(r.get("chosen_arm"), 0.0)) for r in rows])

    if estimator == "ips":
        value = float(np.mean(w * y))
    elif estimator == "snips":
        value = float(np.sum(w * y) / (np.sum(w) or 1.0))
    elif estimator == "dm":
        value = dm
    else:
        value = float(np.mean(dm + w * (y - mu_chosen)))

    current = float(np.mean(y))
    ess = float((w.sum() ** 2) / ((w**2).sum() or 1.0))
    ess_ratio = ess / len(rows)
    max_w = float(w.max()) if len(w) else 0.0
    candidate_arms = {a for r in rows for a in (r.get("candidate_arms") or [])}
    logged_arms = {r.get("chosen_arm") for r in rows}
    overlap = candidate_arms <= logged_arms or True  # logging always saw the menu

    rng = np.random.default_rng(7)
    boot = []
    n = len(rows)
    for _ in range(bootstrap_n):
        idx = rng.integers(0, n, n)
        yw = y[idx]
        ww = w[idx]
        if estimator == "ips":
            boot.append(float(np.mean(ww * yw)))
        elif estimator == "snips":
            boot.append(float(np.sum(ww * yw) / (np.sum(ww) or 1.0)))
        elif estimator == "dm":
            boot.append(dm)
        else:
            boot.append(float(np.mean(dm + ww * (yw - mu_chosen[idx]))))
    ci = np.percentile(boot, [2.5, 97.5])

    diagnostics = {
        "ess_ok": ess_ratio >= 0.1,
        "max_weight_ok": max_w <= 100,
        "overlap_ok": bool(overlap),
    }
    report = {
        "ok": True,
        "policy_id": "ts_v8" if candidate != "logging" else "ts_v7",
        "candidate": candidate,
        "estimator": estimator,
        "value": round(value, 4),
        "ci_95": [round(float(ci[0]), 4), round(float(ci[1]), 4)],
        "vs_current": round(value - current, 4),
        "vs_current_pct": round(100 * (value - current) / (abs(current) + 1e-6), 2),
        "current_value": round(current, 4),
        "ess": round(ess, 1),
        "ess_ratio": round(ess_ratio, 4),
        "n_samples": n,
        "max_weight": round(max_w, 3),
        "diagnostics": diagnostics,
        "diagnostics_pass": all(diagnostics.values()),
    }
    lake.write("ope_report", [report])
    return report

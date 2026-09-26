from __future__ import annotations

import math
from collections import Counter

import numpy as np

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import BanditResult, DecisionContext
from pricing_decision.core.tracing import stage_span


class BanditStage:
    """Stage 5 — contextual Thompson sampling + propensity."""

    def __init__(self, cfg: RuntimeConfig, rng: np.random.Generator | None = None, *, fail: bool = False):
        self.cfg = cfg
        self.rng = rng or np.random.default_rng(7)
        self.fail = fail
        self._decision_count = 0

    def run(self, ctx: DecisionContext) -> DecisionContext:
        with stage_span(ctx, "bandit"):
            if self.fail:
                ctx.bandit = self._epsilon_greedy(ctx, forced=True)
                ctx.mark_degraded("bandit_fallback")
                return ctx

            scores = ctx.score_map()
            if not scores:
                ctx.bandit = self._epsilon_greedy(ctx, forced=True)
                ctx.mark_degraded("bandit_fallback")
                return ctx

            self._decision_count += 1
            exploit = (ctx.request.mode or "live") == "exploit"
            epsilon = 0.0 if exploit else self.cfg.settings.epsilon
            forced = (not exploit) and self._decision_count % 20 == 0
            explore = (not exploit) and (forced or float(self.rng.random()) < epsilon)

            if exploit:
                chosen = max(ctx.arms, key=lambda a: scores[a.id].mu).id
                sampled = {arm.id: float(scores[arm.id].mu) for arm in ctx.arms if arm.id in scores}
                exploration_flag = False
            elif explore:
                chosen = str(self.rng.choice([a.id for a in ctx.arms]))
                sampled = {arm.id: float(scores[arm.id].mu) for arm in ctx.arms if arm.id in scores}
                exploration_flag = True
            else:
                sampled = {}
                all_zero = all(scores[a.id].sigma == 0 for a in ctx.arms if a.id in scores)
                best = -math.inf
                chosen = ctx.arms[0].id
                ties = 0
                for arm in ctx.arms:
                    s = scores[arm.id]
                    sigma_total = math.sqrt(s.sigma**2 + self._bandit_sigma(ctx, arm.id) ** 2)
                    draw = float(s.mu) if all_zero else float(self.rng.normal(s.mu, max(sigma_total, 1e-6)))
                    sampled[arm.id] = draw
                    if math.isclose(draw, best):
                        ties += 1
                    if draw > best:
                        best = draw
                        chosen = arm.id
                        ties = 0
                exploration_flag = False
                if ties:
                    # Random tiebreak among equals is already implicit in sampling; log it.
                    metrics.inc("pds_arm_distribution", {"arm": "tie"})

            propensity = self._propensity(ctx, scores, chosen)
            propensity = max(propensity, self.cfg.settings.propensity_floor)

            ctx.bandit = BanditResult(
                chosen_arm=chosen,
                propensity=round(float(propensity), 4),
                exploration_flag=explore or exploration_flag,
                sampled_scores={k: round(v, 4) for k, v in sampled.items()},
                bandit_version=ctx.versions.bandit_version,
            )
            metrics.inc("pds_arm_distribution", {"arm": chosen})
            metrics.observe("pds_propensity_histogram", propensity)
            if ctx.bandit.exploration_flag:
                metrics.inc("pds_exploration_rate")
        return ctx

    def _bandit_sigma(self, ctx: DecisionContext, arm_id: str) -> float:
        # Cold-start / unseen arm bonus. A real LinTS backend would use sqrt(x A^{-1} x).
        if ctx.features and ctx.features.missing_flags.get("orders_lifetime"):
            return 0.8
        if arm_id not in {a.id for a in ctx.arms}:
            return 1.2
        return 0.15

    def _propensity(self, ctx: DecisionContext, scores: dict, chosen: str) -> float:
        arms = [a.id for a in ctx.arms if a.id in scores]
        if len(arms) == 1:
            return 1.0
        if all(scores[a].sigma == 0 for a in arms):
            return 1.0 if chosen == max(arms, key=lambda a: scores[a].mu) else self.cfg.settings.propensity_floor

        if len(arms) == 2:
            a, b = arms
            if chosen not in (a, b):
                return self.cfg.settings.propensity_floor
            winner, loser = (a, b) if chosen == a else (b, a)
            denom = math.sqrt(scores[winner].sigma ** 2 + scores[loser].sigma ** 2)
            if denom == 0:
                return 1.0
            z = (scores[winner].mu - scores[loser].mu) / denom
            return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

        n = self.cfg.settings.propensity_mc_samples
        wins: Counter[str] = Counter()
        for _ in range(n):
            draws = {a: float(self.rng.normal(scores[a].mu, max(scores[a].sigma, 1e-6))) for a in arms}
            wins[max(draws, key=draws.get)] += 1
        return wins[chosen] / n

    def _epsilon_greedy(self, ctx: DecisionContext, forced: bool = False) -> BanditResult:
        scores = ctx.score_map()
        if scores and not forced:
            chosen = max(ctx.arms, key=lambda a: scores.get(a.id).mu if scores.get(a.id) else -math.inf).id
            explore = False
        else:
            chosen = str(self.rng.choice([a.id for a in ctx.arms])) if ctx.arms else "disc_0"
            explore = True
        n = max(len(ctx.arms), 1)
        return BanditResult(
            chosen_arm=chosen,
            propensity=round(max(1.0 / n, self.cfg.settings.propensity_floor), 4),
            exploration_flag=explore,
            sampled_scores={},
            bandit_version=ctx.versions.bandit_version,
        )

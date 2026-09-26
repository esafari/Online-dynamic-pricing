import numpy as np

from pricing_decision.core.models import CausalScore
from pricing_decision.stages.stage5_bandit import BanditStage


def test_causal_scores_every_arm(orch, sample_request):
    decision = orch.decide(sample_request)
    assert len(decision.context.scores) == len(decision.context.arms)
    assert all(s.sigma > 0 for s in decision.context.scores)
    assert all(s.percentile_10 is not None for s in decision.context.scores)


def test_bandit_propensity_bounded(orch, sample_request):
    decision = orch.decide(sample_request)
    p = decision.context.bandit.propensity
    assert 0.05 <= p <= 1.0
    assert decision.context.bandit.chosen_arm in {a.id for a in decision.context.arms}


def test_propensity_never_zero_when_sigma_zero(orch):
    ctx = orch.ingestion.run({"sku": "SKU-1234", "customer_id": "c_91823"})
    ctx = orch.preprocess.run(ctx)
    ctx = orch.guardrails.run(ctx)
    ctx = orch.candidates.run(ctx)
    ctx.scores = [
        CausalScore(arm_id=a.id, price=a.price, mu=float(i), sigma=0.0)
        for i, a in enumerate(ctx.arms)
    ]
    stage = BanditStage(orch.cfg, rng=np.random.default_rng(0))
    ctx = stage.run(ctx)
    assert ctx.bandit.propensity >= orch.cfg.settings.propensity_floor


def test_bandit_failure_falls_back(orch, sample_request):
    orch.bandit.fail = True
    decision = orch.decide(sample_request)
    assert decision.response.price > 0
    assert "bandit_fallback" in decision.context.degraded_reasons

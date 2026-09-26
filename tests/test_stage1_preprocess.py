def test_known_customer_features(orch, sample_request):
    decision = orch.decide(sample_request)
    raw = decision.context.features.x_raw
    assert raw["segment"] == "returning"
    assert raw["sessions_7d"] == 3
    assert decision.context.features.consent is True
    assert decision.context.features.x_hash.startswith("sha256:")
    assert "email" not in raw


def test_consent_false_strips_personalization(orch, sample_request):
    sample_request["customer_id"] = "c_noconsent"
    decision = orch.decide(sample_request)
    assert decision.context.features.consent is False
    # Generic defaults replace personalization features.
    assert decision.context.features.x_raw["price_sensitivity_score"] == 0.5


def test_cold_start_new_customer(orch, sample_request):
    sample_request["customer_id"] = "c_brand_new"
    decision = orch.decide(sample_request)
    assert decision.context.segment == "new"
    assert decision.context.features.missing_flags.get("orders_lifetime") is True


def test_feature_store_down_degrades(orch, sample_request):
    orch.feature_store.fail = True
    decision = orch.decide(sample_request)
    assert decision.context.degraded is True
    assert "degraded_features" in decision.context.degraded_reasons
    assert decision.response.price > 0

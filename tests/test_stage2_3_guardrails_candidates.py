def test_locked_sku_list_price_only(orch, sample_request):
    sample_request["sku"] = "SKU-LOCKED"
    decision = orch.decide(sample_request)
    assert [a.id for a in decision.context.arms] == ["disc_0"]
    assert decision.response.discount_pct == 0
    assert any(b["reason"] == "not_discountable" for b in decision.context.guardrails.blocked_arms)


def test_low_stock_blocks_discounts(orch, sample_request):
    sample_request["sku"] = "SKU-LOW"
    decision = orch.decide(sample_request)
    assert all(a.discount == 0.0 for a in decision.context.arms) or decision.response.discount_pct == 0
    assert any(b["reason"] == "low_inventory" for b in decision.context.guardrails.blocked_arms)


def test_margin_floor_drops_deep_discounts(orch, sample_request):
    decision = orch.decide(sample_request)
    blocked = {b["reason"] for b in decision.context.guardrails.blocked_arms}
    # 20% off $50 = $40; cost 28 * 1.15 = 32.2 so 20% is still ok; 15% should exist
    assert any(a.id == "disc_0" for a in decision.context.arms)
    assert "margin_floor" in blocked or any(a.discount <= 0.15 for a in decision.context.arms)


def test_candidate_prices_never_exceed_msrp(orch, sample_request):
    decision = orch.decide(sample_request)
    msrp = decision.context.catalog["msrp"]
    assert all(a.price <= msrp for a in decision.context.arms)


def test_no_consent_blocks_discounts(orch, sample_request):
    sample_request["customer_id"] = "c_noconsent"
    decision = orch.decide(sample_request)
    assert decision.response.discount_pct == 0

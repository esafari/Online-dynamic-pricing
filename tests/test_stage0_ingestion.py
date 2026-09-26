from pricing_decision.core.exceptions import SkuNotFoundError, ValidationFailedError


def test_missing_sku_is_400(orch):
    try:
        orch.decide({"customer_id": "c_91823"})
        raise AssertionError("expected validation error")
    except ValidationFailedError as exc:
        assert exc.status_code == 400
        assert exc.reason == "missing_sku"


def test_unknown_sku_is_404(orch, sample_request):
    sample_request["sku"] = "SKU-NOPE"
    try:
        orch.decide(sample_request)
        raise AssertionError("expected sku error")
    except SkuNotFoundError as exc:
        assert exc.status_code == 404


def test_missing_customer_is_guest(orch, sample_request):
    sample_request.pop("customer_id")
    decision = orch.decide(sample_request)
    assert decision.context.segment == "guest"


def test_idempotent_replay(orch, sample_request):
    first = orch.decide(sample_request)
    sample_request["decision_id"] = first.context.decision_id
    second = orch.decide(sample_request)
    assert second.context.idempotent_hit is True
    assert second.response.decision_id == first.response.decision_id


def test_server_time_wins_on_clock_skew(orch, sample_request):
    sample_request["ts"] = "2010-01-01T00:00:00Z"
    decision = orch.decide(sample_request)
    assert decision.context.client_ts.year == 2010
    assert decision.context.received_at.year >= 2026

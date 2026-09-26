from fastapi.testclient import TestClient

from pricing_decision.api.app import create_app


def test_client_response_hides_internals(orch, sample_request):
    decision = orch.decide(sample_request)
    payload = decision.response.model_dump()
    assert "propensity" not in payload
    assert "causal_model_id" not in payload
    assert "policy_id" not in payload
    assert payload["decision_id"] == decision.context.decision_id
    assert payload["expires_at"] is not None


def test_experience_has_ope_fields(orch, sample_request):
    decision = orch.decide(sample_request)
    exp = decision.experience
    assert exp["propensity"] >= 0.05
    assert exp["chosen_arm"]
    assert exp["candidate_arms"]
    assert exp["policy_id"]
    assert exp["causal_model_id"]
    assert exp["context_hash"].startswith("sha256:")


def test_vip_hides_badge(orch, sample_request):
    sample_request["customer_id"] = "c_vip"
    sample_request["sku"] = "SKU-VIP"
    decision = orch.decide(sample_request)
    if decision.response.discount_pct > 0:
        assert decision.response.badge is None


def test_http_price_and_health(orch, sample_request):
    client = TestClient(create_app(orch))
    page = client.get("/")
    assert page.status_code == 200
    assert "Pricing Decision Service" in page.text

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    bad = client.post("/v1/price", json={"customer_id": "x"})
    assert bad.status_code == 400

    missing = client.post("/v1/price", json={"sku": "NOPE", "customer_id": "c_91823"})
    assert missing.status_code == 404

    ok = client.post("/v1/price", json=sample_request)
    assert ok.status_code == 200
    body = ok.json()
    assert body["price"] > 0
    assert "propensity" not in body
    assert body["currency"] in {"USD", "CAD", "EUR"}

    catalog = client.get("/v1/catalog")
    assert catalog.status_code == 200
    names = {p["display_name"] for p in catalog.json()["profiles"]}
    assert {"Maya Chen", "James Cole", "Priya Shah", "Alex Rivera", "Noah Kim", "Guest shopper"} <= names
    skus = {s["sku"] for s in catalog.json()["skus"]}
    assert {"SKU-1234", "SKU-CASE", "SKU-LOCKED"} <= skus

    board = client.get("/v1/price-board")
    assert board.status_code == 200
    data = board.json()
    assert len(data["cells"]) == len(data["profiles"]) * len(data["skus"])
    maya_buds = next(
        c for c in data["cells"] if c["customer_id"] == "c_maya" and c["sku"] == "SKU-1234"
    )
    alex_buds = next(
        c for c in data["cells"] if c["customer_id"] == "c_alex" and c["sku"] == "SKU-1234"
    )
    locked = next(c for c in data["cells"] if c["sku"] == "SKU-LOCKED")
    assert maya_buds["price"] > 0
    assert alex_buds["discount_pct"] == 0
    assert locked["discount_pct"] == 0

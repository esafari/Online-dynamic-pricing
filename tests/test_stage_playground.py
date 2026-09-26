from fastapi.testclient import TestClient

from pricing_decision.api.app import create_app


def test_stage_docs_and_ingestion_validation(orch):
    client = TestClient(create_app(orch))
    meta = client.get("/v1/stages")
    assert meta.status_code == 200
    ids = [s["id"] for s in meta.json()["stages"]]
    assert ids[0] == "board"
    assert "guardrails" in ids
    assert "bandit" in ids
    guard = next(s for s in meta.json()["stages"] if s["id"] == "guardrails")
    assert guard["in_short"]
    assert guard["process"][0]["title"]
    assert "minimum margin" in guard["process"][1]["detail"]

    missing = client.post("/v1/stages/run", json={"stage": "ingestion", "request": {"customer_id": "c_maya"}})
    body = missing.json()
    assert body["ok"] is False
    assert body["error"]["status_code"] == 400


def test_guardrail_and_preprocess_overrides(orch):
    client = TestClient(create_app(orch))
    blocked = client.post(
        "/v1/stages/run",
        json={
            "stage": "guardrails",
            "request": {"customer_id": "c_maya", "sku": "SKU-1234", "cart_value": 50, "mode": "exploit"},
            "overrides": {"min_margin": 0.8, "stock": 100},
        },
    ).json()
    assert blocked["ok"] is True
    reasons = {b["reason"] for b in blocked["guardrails"]["blocked_arms"]}
    assert "margin_floor" in reasons

    generic = client.post(
        "/v1/stages/run",
        json={
            "stage": "preprocess",
            "request": {"customer_id": "c_maya", "sku": "SKU-1234", "mode": "exploit"},
            "overrides": {"consent": False},
        },
    ).json()
    assert generic["features"]["consent"] is False
    assert generic["features"]["x_raw"]["price_sensitivity_score"] == 0.5


def test_exploit_bandit_is_deterministic(orch):
    client = TestClient(create_app(orch))
    payload = {
        "stage": "bandit",
        "request": {"customer_id": "c_maya", "sku": "SKU-CASE", "cart_value": 29, "mode": "exploit"},
        "overrides": {},
    }
    first = client.post("/v1/stages/run", json=payload).json()
    second = client.post("/v1/stages/run", json=payload).json()
    assert first["bandit"]["chosen_arm"] == second["bandit"]["chosen_arm"]
    assert first["bandit"]["exploration_flag"] is False

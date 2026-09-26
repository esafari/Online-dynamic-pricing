from fastapi.testclient import TestClient

from pricing_decision.api.app import create_app


def test_architecture_includes_missing_layers(orch):
    client = TestClient(create_app(orch))
    arch = client.get("/v1/architecture")
    assert arch.status_code == 200
    body = arch.json()
    ids = {s["id"] for s in body["stages"]}
    assert {"arch_map", "arch_azure", "arch_layers", "arch_usecases", "arch_monitor", "arch_gaps"} <= ids
    layer_ids = {layer["id"] for layer in body["layers"]}
    assert {"gateway", "catalog", "offers", "experiments", "monitor", "support", "control", "consistency", "batch"} <= layer_ids
    assert any("catalog" in x.lower() or "Coupon" in x for x in body["added_vs_typical_brain_diagram"])
    assert body["gaps_in_original_doc"]
    assert any("stickiness" in g["title"].lower() or "sticky" in g["title"].lower() for g in body["gaps_in_original_doc"])

    azure = client.get("/azure")
    assert azure.status_code == 200
    assert b"Container Apps" in azure.content
    stages = client.get("/v1/azure/stages")
    assert stages.status_code == 200
    assert stages.json()["stages"][0]["id"] == "kids"
    ids = {s["id"] for s in stages.json()["stages"]}
    assert "components" in ids
    project = client.get("/project")
    assert project.status_code == 200
    assert b"src/pricing_decision/api/app.py" in project.content
    assert b"orchestrator.py" in project.content
    proj_stages = client.get("/v1/project/stages")
    assert proj_stages.status_code == 200
    assert proj_stages.json()["stages"][0]["id"] == "overview"
    proj_ids = {s["id"] for s in proj_stages.json()["stages"]}
    assert {"api", "stages", "services", "configs", "data"} <= proj_ids
    science = client.get("/science")
    assert science.status_code == 200
    assert b"because we change a price" in science.content
    assert b"off-policy" in science.content.lower()
    sci_stages = client.get("/v1/science/stages")
    assert sci_stages.status_code == 200
    assert sci_stages.json()["stages"][0]["id"] == "different"
    sci_ids = {s["id"] for s in sci_stages.json()["stages"]}
    assert {"because", "uncertainty", "explore", "challenger", "constraints", "champion", "loop"} <= sci_ids
    sm = client.get("/sagemaker")
    assert sm.status_code == 200
    assert b"SageMaker" in sm.content
    assert b"OfflinePipeline" in sm.content
    sm_stages = client.get("/v1/sagemaker/stages")
    assert sm_stages.status_code == 200
    assert sm_stages.json()["stages"][0]["id"] == "what"
    sm_ids = {s["id"] for s in sm_stages.json()["stages"]}
    assert {"bucket", "train", "ope", "registry", "pipeline", "pins"} <= sm_ids
    comps = client.get("/v1/azure/components")
    assert comps.status_code == 200
    catalog = comps.json()["components"]
    names = {c["id"] for c in catalog}
    assert {"ca", "redis", "cosmos", "evh_ns", "adls", "mlw", "appcs", "kv"} <= names


def test_holdout_and_use_case(orch):
    client = TestClient(create_app(orch))
    holdout = client.post(
        "/v1/price:explain",
        json={"customer_id": "c_maya", "sku": "SKU-1234", "cart_value": 50, "experiment_hint": "holdout"},
    )
    assert holdout.status_code == 200
    arms = [a["id"] for a in holdout.json()["arms"]]
    assert arms == ["disc_0"]

    uc = client.post("/v1/use-cases/uc1_pdp", json={})
    assert uc.status_code == 200
    assert uc.json()["response"]["price"] > 0

    missing = client.post("/v1/use-cases/uc_nope", json={})
    assert missing.status_code == 404


def test_outcome_and_monitor(orch):
    client = TestClient(create_app(orch))
    priced = client.post("/v1/price", json={"customer_id": "c_maya", "sku": "SKU-1234", "cart_value": 50})
    decision_id = priced.json()["decision_id"]
    out = client.post(
        "/v1/outcomes",
        json={"decision_id": decision_id, "event_type": "purchase", "revenue": 45.0, "margin": 12.0, "units": 1},
    )
    assert out.status_code == 200
    lookup = client.get(f"/v1/decisions/{decision_id}")
    assert lookup.status_code == 200
    mon = client.get("/v1/monitor")
    assert mon.status_code == 200
    assert "nfrs" in mon.json()
    assert "control" in mon.json()


def test_control_plane_kill_switch_and_budget(orch):
    client = TestClient(create_app(orch))
    killed = client.post("/v1/use-cases/uc13_killswitch", json={})
    assert killed.status_code == 200
    assert killed.json()["arm"] == "disc_0"
    assert killed.json()["response"]["price"] == 50.0
    assert client.get("/v1/control").json()["kill_switch"] is False

    budget = client.post("/v1/use-cases/uc15_budget", json={})
    assert budget.status_code == 200
    assert budget.json()["arm"] == "disc_0"


def test_sticky_price_and_offer_ledger(orch):
    client = TestClient(create_app(orch))
    sticky = client.post("/v1/use-cases/uc14_sticky", json={})
    assert sticky.status_code == 200
    body = sticky.json()
    assert body["sticky"]["same_price"] is True
    assert body["sticky"]["replayed"] is True

    campaign = client.post("/v1/use-cases/uc12_campaign", json={})
    assert campaign.status_code == 200
    assert len(campaign.json()["batch"]) == 3

    code = orch.coupons.issue("c_maya", 0.10, sku="SKU-1234", price=44.99, decision_id="d_ledger")
    found = client.get(f"/v1/offers/{code}")
    assert found.status_code == 200
    assert found.json()["offer"]["honored_after_policy_change"] is True
    honoured = client.post(f"/v1/offers/{code}/redeem")
    assert honoured.status_code == 200
    again = client.post(f"/v1/offers/{code}/redeem")
    assert again.status_code == 400


def test_batch_and_fx_localization(orch):
    client = TestClient(create_app(orch))
    batch = client.post(
        "/v1/price:batch",
        json={"requests": [
            {"customer_id": "c_maya", "sku": "SKU-1234", "cart_value": 50, "mode": "exploit"},
            {"customer_id": "c_james", "sku": "SKU-VIP", "cart_value": 199, "mode": "exploit"},
        ]},
    )
    assert batch.status_code == 200
    assert batch.json()["n"] == 2

    usd = client.post(
        "/v1/price",
        json={"customer_id": "c_noah", "sku": "SKU-CASE", "cart_value": 29, "mode": "exploit"},
    )
    cad = client.post(
        "/v1/price",
        json={"customer_id": "c_noah", "sku": "SKU-CASE", "cart_value": 29, "currency": "CAD", "mode": "exploit"},
    )
    assert cad.status_code == 200
    assert cad.json()["currency"] == "CAD"
    assert abs(cad.json()["price"] - usd.json()["price"] * 1.35) < 0.03

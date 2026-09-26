from pathlib import Path

from fastapi.testclient import TestClient

from pricing_decision.api.app import create_app
from pricing_decision.offline.lake import LakeHouse
from pricing_decision.offline.pipeline import OfflinePipeline


def test_offline_docs_and_seeded_flow(orch, tmp_path: Path):
    pipe = OfflinePipeline(orch, lake=LakeHouse(tmp_path / "lake"), registry=None)
    from pricing_decision.offline.registry import ModelRegistry

    pipe.registry = ModelRegistry(tmp_path / "registry")

    ingested = pipe.run("ol_ingest", {"seed_n": 48, "include_live_logs": False})
    assert ingested["ok"] is True
    assert ingested["decisions"] >= 48

    joined = pipe.run("ol_join", {"reward_type": "margin"})
    assert joined["n_labeled"] >= 40
    assert 0 <= joined["join_match_rate"] <= 1

    filled = pipe.run("ol_backfill", {})
    assert filled["n_rows"] >= 40
    assert filled["backfill_leakage_detected_total"] == 0

    causal = pipe.run("ol_causal", {"model_type": "dr_learner", "min_arm_n": 3})
    assert causal["ok"] is True
    assert len(causal["arms"]) >= 2

    bandit = pipe.run("ol_bandit", {})
    assert bandit["ok"] is True
    assert bandit["n_updates"] > 0

    ope = pipe.run("ol_ope", {"estimator": "dr", "candidate": "logging"})
    assert ope["ok"] is True
    assert ope["n_samples"] > 10
    assert "value" in ope

    registered = pipe.run("ol_registry", {})
    assert registered["ok"] is True

    gate = pipe.run("ol_gate", {})
    assert gate["ok"] is True
    assert "can_deploy" in gate
    assert "checks" in gate


def test_offline_http_surface(orch, tmp_path: Path):
    client = TestClient(create_app(orch))
    docs = client.get("/v1/offline/stages")
    assert docs.status_code == 200
    ids = [s["id"] for s in docs.json()["stages"]]
    assert ids[0] == "ol_overview"
    assert "ol_ope" in ids
    assert docs.json()["stages"][1]["process"][0]["title"]

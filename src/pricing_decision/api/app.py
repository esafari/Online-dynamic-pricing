from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from pricing_decision import __version__
from pricing_decision.core.exceptions import PricingError
from pricing_decision.core.metrics import metrics
from pricing_decision.architecture import (
    architecture_tabs,
    azure_components,
    azure_tabs,
    project_tabs,
    sagemaker_tabs,
    science_tabs,
)
from pricing_decision.offline.pipeline import OfflinePipeline, offline_stage_catalog
from pricing_decision.orchestrator import PricingOrchestrator
from pricing_decision.platform import architecture_view, lookup_decision, monitor_snapshot, run_use_case
from pricing_decision.playground import StagePlayground, stage_catalog
from pricing_decision.services.outcomes import OutcomeService

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
REPO_ROOT = Path(__file__).resolve().parents[3]


def create_app(orchestrator: PricingOrchestrator | None = None) -> FastAPI:
    app = FastAPI(title="Pricing Decision Service", version=__version__)
    orch = orchestrator or PricingOrchestrator()
    playground = StagePlayground(orch)
    offline = OfflinePipeline(orch)
    outcomes = OutcomeService(offline.lake)
    app.state.orchestrator = orch
    app.state.playground = playground
    app.state.offline = offline
    app.state.outcomes = outcomes

    @app.get("/")
    def home() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/azure")
    def azure_runbook() -> FileResponse:
        return FileResponse(REPO_ROOT / "docs" / "azure-implementation.html")

    @app.get("/project")
    def project_map() -> FileResponse:
        """Folder-and-file map for the lab Project tab."""
        return FileResponse(REPO_ROOT / "docs" / "project-map.html")

    @app.get("/v1/azure/stages")
    def azure_stages() -> dict[str, Any]:
        return {"stages": azure_tabs()}

    @app.get("/v1/project/stages")
    def project_stages() -> dict[str, Any]:
        return {"stages": project_tabs()}

    @app.get("/science")
    def science_map() -> FileResponse:
        """Job-description science map: causal, bandits, OPE, constraints."""
        return FileResponse(REPO_ROOT / "docs" / "science.html")

    @app.get("/v1/science/stages")
    def science_stages() -> dict[str, Any]:
        return {"stages": science_tabs()}

    @app.get("/sagemaker")
    def sagemaker_runbook() -> FileResponse:
        """Step-by-step SageMaker runbook for the offline pipeline."""
        return FileResponse(REPO_ROOT / "docs" / "sagemaker-implementation.html")

    @app.get("/v1/sagemaker/stages")
    def sagemaker_stages() -> dict[str, Any]:
        return {"stages": sagemaker_tabs()}

    @app.get("/v1/azure/components")
    def azure_component_catalog() -> dict[str, Any]:
        return azure_components()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "pins": orch.cache.snapshot()}

    @app.get("/metrics")
    def metrics_snapshot() -> dict[str, Any]:
        return metrics.snapshot()

    @app.get("/v1/catalog")
    def catalog() -> dict[str, Any]:
        return orch.catalog_view()

    @app.get("/v1/price-board")
    def price_board(channel: str = "web", device: str = "mobile") -> dict[str, Any]:
        return orch.price_board(channel=channel, device=device)

    @app.get("/v1/stages")
    def stages() -> dict[str, Any]:
        return {"stages": stage_catalog(), **orch.catalog_view()}

    @app.post("/v1/stages/run")
    def run_stage(payload: dict[str, Any]) -> dict[str, Any]:
        stage = str(payload.get("stage") or "response")
        request = payload.get("request") or {}
        overrides = payload.get("overrides") or {}
        return playground.run(stage=stage, request=request, overrides=overrides)

    @app.post("/v1/stages/reload")
    def reload_stage_cache() -> dict[str, Any]:
        return playground.reload_cache()

    @app.get("/v1/offline/stages")
    def offline_stages() -> dict[str, Any]:
        """Offline learning lab: stage docs plus current lake snapshot."""
        return {"stages": offline_stage_catalog(), "overview": offline.overview()}

    @app.post("/v1/offline/run")
    def run_offline(payload: dict[str, Any]) -> dict[str, Any]:
        stage = str(payload.get("stage") or "ol_overview")
        overrides = payload.get("overrides") or {}
        return offline.run(stage, overrides)

    @app.get("/v1/architecture")
    def architecture() -> dict[str, Any]:
        return {**architecture_view(), "stages": architecture_tabs()}

    @app.post("/v1/use-cases/{use_case_id}")
    def use_case(use_case_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        result = run_use_case(orch, use_case_id, payload or {})
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/v1/outcomes")
    def record_outcome(payload: dict[str, Any]) -> dict[str, Any]:
        result = outcomes.record(payload)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.get("/v1/decisions/{decision_id}")
    def get_decision(decision_id: str) -> dict[str, Any]:
        result = lookup_decision(orch, offline, decision_id)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/v1/monitor")
    def monitor() -> dict[str, Any]:
        return monitor_snapshot(orch, offline)

    @app.get("/v1/control")
    def get_control() -> dict[str, Any]:
        return orch.control.snapshot()

    @app.post("/v1/control")
    def set_control(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return orch.control.update(payload or {})

    @app.post("/v1/price:batch")
    def price_batch(payload: dict[str, Any]) -> dict[str, Any]:
        requests = payload.get("requests") or []
        if not isinstance(requests, list) or not requests:
            raise HTTPException(status_code=400, detail={"reason": "empty_batch"})
        try:
            decisions = orch.decide_batch(requests)
        except PricingError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"reason": exc.reason, "message": exc.message})
        return {
            "n": len(decisions),
            "responses": [d.response.model_dump(mode="json", exclude_none=True) for d in decisions],
        }

    @app.get("/v1/offers/{code}")
    def get_offer(code: str) -> dict[str, Any]:
        rec = orch.coupons.lookup(code)
        if not rec:
            raise HTTPException(status_code=404, detail={"reason": "unknown_offer"})
        return {"ok": True, "offer": rec}

    @app.post("/v1/offers/{code}/redeem")
    def redeem_offer(code: str) -> dict[str, Any]:
        result = orch.coupons.redeem(code)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/v1/price")
    def price(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            decision = orch.decide(payload)
        except PricingError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"reason": exc.reason, "message": exc.message})
        body = decision.response.model_dump(mode="json", exclude_none=True)
        return body

    @app.post("/v1/price:explain")
    def price_explain(payload: dict[str, Any]) -> dict[str, Any]:
        """Internal debug endpoint — not for clients."""
        try:
            decision = orch.decide(payload)
        except PricingError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"reason": exc.reason, "message": exc.message})
        return {
            "response": decision.response.model_dump(mode="json", exclude_none=True),
            "experience": decision.experience,
            "degraded": decision.context.degraded,
            "degraded_reasons": decision.context.degraded_reasons,
            "arms": [a.model_dump() for a in decision.context.arms],
            "scores": [s.model_dump() for s in decision.context.scores],
            "bandit": decision.context.bandit.model_dump() if decision.context.bandit else None,
            "timings_ms": decision.context.stage_timings_ms,
        }

    @app.post("/v1/admin/reload")
    def reload_models() -> dict[str, Any]:
        return orch.cache.hot_reload()

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"reason": "internal_error", "message": str(exc)})

    return app


app = create_app()

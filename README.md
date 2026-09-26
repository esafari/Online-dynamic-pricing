# Causal Personalized Pricing Decision Service

This repository is a working **Pricing Decision Service**. It answers a single operational question: given this shopper, this SKU, and this moment, what price should we show, and how do we learn from that choice later?

Most machine learning systems learn from a dataset collected by someone else. Here the model *intervenes*. When it shows Maya a 10% discount on SKU-1234, that choice changes whether she buys, what margin lands, and which row appears in tomorrow’s training file. The loop is decision → intervention → outcome → learning → a better decision.

The online path is FastAPI. A request is ingested, identity and features are resolved, guardrails drop illegal prices, a causal model scores what remains, a bandit selects an arm, a coupon is bound, the decision is logged with a **propensity**, and the client receives only a safe JSON body (price, badge, coupon, reason codes, `decision_id`). Propensity, model ids, and scores never leave on that response.

The offline path is the night shift. Logs are joined to purchases on `decision_id`, features are reconstructed as of the decision timestamp, a causal model and a bandit are updated, off-policy evaluation (IPS / SNIPS / DR) estimates a challenger **before** it sees 100% of checkout, and a gate can refuse to ship. Holdout traffic still exists so you can estimate causal effects, not only bandit regret.

**Resume one-liner:** *Built a FastAPI pricing system that chooses a constrained, personalized price with causal scoring and Thompson sampling, then evaluates challenger policies with off-policy evaluation (IPS/DR) before shadow and canary rollout.*

---

## What this system is built to answer

These are the research and product questions the code is organized around (also the **Science** tab in the lab).

- **Because we changed a price, not “what happened next.”** Stage 4 predicts expected reward μ(x, a), not a generic conversion score. Holdout forces list price so a clean causal baseline remains after the bandit takes over the rest of the store.
- **How uncertainty should affect the decision.** The S-learner returns σ. Thompson sampling draws from that posterior. High uncertainty buys information; certainty harvests margin. If the log is down, exploration stops.
- **Exploit versus experiment.** Contextual Thompson sampling with a 5% ε floor and a propensity floor of 0.05 so IPS/DR never divide by zero. `mode: exploit` skips randomize. Stickiness and frequency caps stop you from re-randomizing the same person.
- **Value of a challenger before full deploy.** `offline/ope.py` scores a new policy on old logs. The gate in `offline/gate.py` requires DR to beat current, a healthy ESS, fairness, and latency before shadow → 1% → 5% → 100%.
- **Economics under constraints.** Stage 2 removes arms the model is not allowed to want: MAP, margin floor, stock, frequency, consent, competitor band, VIP fairness, daily discount budget, kill switch. List price always stays on the ladder so checkout can fail closed.

Success is not a prettier offline metric. Success is measurable economic lift in a controlled experiment, a loop that learns from its own interventions, and a kill switch that still works at 2 a.m.

---

## Quick start

Python 3.11+ on Windows. From this folder (`Pricing`):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m uvicorn pricing_decision.api.app:app --host 127.0.0.1 --port 8080 --reload
```

Open **http://127.0.0.1:8080/**. That is the lab. One-shot without a browser:

```bash
python -m pricing_decision.cli decide -f examples/request.json --explain
python -m pricing_decision.cli serve
```

Package name in `pyproject.toml` is `pricing-decision-service`. The console script is `pds`. Environment variables use the prefix `PDS_` (host, port, Kafka on/off, log buffer, epsilon).

---

## The lab UI

The home page is `src/pricing_decision/web/index.html`, served by FastAPI at `GET /`. The top row is pipelines:

| Tab | What it is |
|---|---|
| **Project** | Folder and file map (`/project`) |
| **Science** | The questions above, mapped onto this code (`/science`) |
| **Azure** | Canada Central production runbook (`/azure`) |
| **SageMaker** | Step-by-step overnight training on AWS (`/sagemaker`) |
| **Architecture** | Layers, use cases, monitor, gaps |
| **Online PDS** | Stages 0–10 you can run on Maya / SKU-1234 |
| **Offline learning** | Ingest → join → backfill → causal → bandit → OPE → gate |

---

## Online pipeline (checkout, p99 target under 100 ms)

`PricingOrchestrator.decide()` in `src/pricing_decision/orchestrator.py` walks these stages. Do not rewrite them to “be Azure” or “be SageMaker.”

| Stage | File | Role |
|---|---|---|
| 0 Ingestion | `stages/stage0_ingestion.py` | Validate, pin versions, idempotency, attach trace |
| 1 Preprocess | `stages/stage1_preprocess.py` | Identity, consent, feature vector `x` |
| 2 Guardrails | `stages/stage2_guardrails.py` | Drop illegal prices before anyone scores them |
| 3 Candidates | `stages/stage3_candidates.py` | Discrete discount arms that survived |
| 4 Causal | `stages/stage4_causal.py` | S-learner μ(x, a) and σ (margin / revenue / LTV / composite) |
| 5 Bandit | `stages/stage5_bandit.py` | Contextual Thompson sampling + propensity |
| 6 Post-process | `stages/stage6_postprocess.py` | Charm price, coupon, stickiness |
| 7 Logging | `stages/stage7_logging.py` | Experience tuple; must not block checkout |
| 8 Response | `stages/stage8_response.py` | Safe client JSON only |
| 9 Fallback | `stages/stage9_fallback.py` | Still return a price when a dependency is sick |
| 10 Cache | `stages/stage10_cache.py` | Version pins and hot reload |

Default reward is expected margin `(price − cost) × P(purchase)`. Default policy is Thompson sampling with ε = 0.05 and propensity floor 0.05.

### Fallback ladder

Full pipeline → cached causal scores on timeout → segment defaults if features are down → ε-greedy if the bandit errors → list price if every discount is blocked → static catalog price. Degraded rows are marked `exclude_from_training` so they do not poison OPE.

If Event Hubs / Kafka / the log is down, buffer locally and **stop exploring**. An unlogged experiment is not an experiment.

---

## Offline pipeline (night shift)

`src/pricing_decision/offline/pipeline.py` is the conductor. On the laptop the lake is `data/lake/*.jsonl`. The live buffer is `data/log_buffer/decisions.jsonl`. The tiny registry is `data/registry/models.json`.

| Step | Module | Role |
|---|---|---|
| Ingest | `offline/ingest.py` | Land decisions and outcomes once each |
| Join | `offline/join.py` | Match on `decision_id`, reward window, net refunds |
| Backfill | `offline/backfill.py` | Features **as of** the decision timestamp, not “current” |
| Causal | `offline/causal.py` | Train the scorer used online |
| Bandit | `offline/bandit.py` | Update the policy posterior |
| OPE | `offline/ope.py` | IPS, SNIPS, DR, bootstrap CI, ESS |
| Fairness / drift | `offline/fairness.py`, `drift.py` | Segment price gaps, PSI |
| Registry | `offline/registry.py` | Store the artifact |
| Gate | `offline/gate.py` | Promote only if OPE + fairness + latency pass |
| Rollout | `offline/rollout.py` | Shadow → canary → ramp, or keep champion |

Join on `customer_id` alone mixes people and ruins OPE. Join on `decision_id`.

---

## HTTP API

FastAPI lives in `src/pricing_decision/api/app.py` (`create_app()`, then `app = create_app()`). Uvicorn loads `pricing_decision.api.app:app`. Docker does the same on port 8080.

| Method | Path | Audience |
|---|---|---|
| GET | `/` | Lab UI |
| GET | `/health` | Liveness |
| GET | `/docs` | OpenAPI |
| POST | `/v1/price` | Channels — client fields only |
| POST | `/v1/price:explain` | **Internal** — scores leak; never public |
| POST | `/v1/price:batch` | Campaigns |
| POST | `/v1/outcomes` | Purchase / refund keyed by `decision_id` |
| GET | `/v1/decisions/{id}` | CS lookup |
| GET/POST | `/v1/control` | Kill switch, freeze, budget |
| GET | `/v1/offers/{code}` + redeem | Offer ledger |
| POST | `/v1/admin/reload` | Hot-reload pins |

Example request (`examples/request.json`):

```json
{
  "customer_id": "c_91823",
  "session_id": "s_abc",
  "sku": "SKU-1234",
  "cart_value": 50.0,
  "channel": "web",
  "device": "mobile",
  "geo": "CA-ON",
  "ts": "2026-09-11T14:22:01Z"
}
```

Example client response: `price`, `currency`, `discount_pct`, `badge`, `coupon_code`, `reason_codes`, `decision_id`, `expires_at`. No propensity.

---

## Demo catalog

Defined in `configs/catalog.yaml`. Missing `customer_id` is **guest**. Unknown SKU is **404**.

| ID | Role |
|---|---|
| `c_maya` / `c_91823` + `SKU-1234` | Happy path, list 50 |
| `c_vip` | Narrower ladder |
| `c_risk` | At-risk, deeper discounts if legal |
| `c_noconsent` | Consent off → generic `x` / list-like treatment |
| `SKU-LOW` | Low stock → discounts blocked |
| `SKU-LOCKED` | Not discountable → list price |

Use cases (kill switch, sticky, budget, holdout, batch) live in `configs/use_cases.yaml` and the Architecture tab.

---

## Folder map

```
Pricing/
  pyproject.toml              package, deps, pytest, `pds` CLI
  README.md                   this file
  Dockerfile                  image for Container Apps / ECS / SageMaker jobs
  configs/                    YAML the running service reads
  src/pricing_decision/       the only Python package you maintain
    api/app.py                FastAPI
    web/index.html            lab UI
    orchestrator.py           wires stages 0–10
    stages/                   online pipeline
    services/                 adapters you swap for Azure / AWS
    core/                     request/response models
    offline/                  lake, train, OPE, gate
    cli.py                    serve / decide
  data/                       generated logs and lake (not source of truth)
  tests/                      pytest
  docs/                       Azure, SageMaker, Project, Science HTML
  infra/                      Azure deploy scripts
  examples/request.json
```

Ignore `.venv`, `.pytest_cache`, and `src/*.egg-info`. They are install artifacts.

**Adapters you change for production** (keep stage files): `services/feature_store.py` → Redis / ElastiCache; `services/catalog.py`, `identity.py`, `coupon.py` → Cosmos or DynamoDB; `services/control_plane.py` → App Configuration or AWS AppConfig; `services/logger.py` → Event Hubs / MSK / Kinesis (`PDS_KAFKA_ENABLED`); `offline/lake.py` → ADLS or S3; `offline/registry.py` → Azure ML or SageMaker Model Registry.

---

## Config

Everything under `configs/` is what the process reads without a code edit.

| File | Role |
|---|---|
| `catalog.yaml` | SKUs and customer snapshots |
| `guardrails.yaml` | MAP, margin, frequency, inventory, fairness |
| `ladders.yaml` | Discount arms per segment |
| `features.yaml` | Feature contract, TTLs, defaults |
| `control_plane.yaml` | Kill switch, freeze, sticky TTL, daily budget |
| `versions.yaml` | Policy / causal / guardrail pins |
| `segments.yaml` | Shopper types |
| `stages.yaml` / `offline_stages.yaml` | Lab left-nav copy |
| `use_cases.yaml` | Architecture demos |
| `architecture.yaml` | Layers and gaps |
| `azure_*.yaml` / `science.yaml` / `sagemaker.yaml` / `project_map.yaml` | Lab tab navigation |

In-flight requests keep the pins attached at ingestion, so `POST /v1/admin/reload` cannot change a decision mid-flight.

---

## Azure (production shape)

The **Azure** tab (`docs/azure-implementation.html`) is the Canada Central runbook. Same brain, hosted.

FastAPI → Container Apps + ACR. Gateway → Front Door + APIM (explain stays internal). Features / sticky → Redis. Catalog / identity / offers → Cosmos DB. Control plane → App Configuration + Key Vault. Logs → Event Hubs (Kafka) + ADLS. Train / OPE → Azure ML. Metrics → App Insights. Do not start on AKS or Service Bus for this telemetry. Shopper and decision data stay in **Canada Central**; Canada East is DR later.

---

## SageMaker (overnight on AWS)

The **SageMaker** tab (`docs/sagemaker-implementation.html`) is step-by-step. SageMaker replaces the laptop night shift, not checkout.

Create the lake in **`ca-central-1`**. Processing jobs run `ol_ingest`, `ol_join`, `ol_backfill`, `ol_ope`. Training jobs run `ol_causal` and `ol_bandit` on a small CPU using this repo’s Docker image. The Model Registry holds a package that is Approved only if the same gate passes. Pins go back to FastAPI as a canary. Do not wrap `/v1/price` in a SageMaker endpoint on day one. Do not train in `us-east-1` because the instance looks cheaper.

Online hosting on AWS, if you go that way, is ECS Fargate + ECR + ElastiCache + DynamoDB + MSK/Kinesis + S3 — same adapter rule.

---

## Tests

From this folder: `pytest`. The suite covers ingestion, preprocess, guardrails, causal/bandit, response/logging, the playground API, the offline pipeline, and the Architecture / Azure / Project / Science / SageMaker HTML maps.

Mark future cloud integration tests `@pytest.mark.azure` or similar so they skip unless `PDS_ENV` starts with `azure` or `aws`.

---

## What not to do

Do not rewrite `stage4_causal.py` or the bandit to match a cloud brand. Do not train inside the online container. Do not put propensity on the public response. Do not join outcomes only on customer_id. Do not explore when the decision log is incomplete. Do not put PII in a cheaper foreign region. Do not treat a Completed training job as permission to ship — Completed only means the process exited.

The system should become better at operating the business because it has operated the business. That is why every live decision is logged with a propensity.

# Causal Personalized Pricing Decision Service

## What this project is

This repository is a working pricing system you can run on a laptop. Its job is simple to say and hard to do well: **given this shopper, this product, and this moment, what price should we show — and how do we prove later that the choice was a good one?**

Think of a store website. Maya opens a product that lists at $50. The system must decide in a few milliseconds whether she sees $50, $45, or $40. That decision has to stay legal (you cannot go below a vendor’s minimum advertised price, you cannot sell below cost, you cannot empty the warehouse). It also has to be *learnable*: if we showed her $45, we need to remember how likely that price was, so tonight we can ask “would a different policy have made more money?” without putting the new policy in front of every customer.

That is the difference from ordinary machine learning. A typical model learns from a spreadsheet of things that already happened. This model **changes what happens next**. The discount it shows changes whether Maya buys, which changes tomorrow’s training data. The loop is: decide a price → the shopper sees it (an intervention) → we later see purchase or refund (an outcome) → we learn → we decide better next time.

There are two halves of the product.

The **online** half is the checkout brain. It runs in FastAPI and must answer in well under 100 milliseconds. It validates the request, looks up who the shopper is, throws away illegal prices, scores the rest, picks one, binds a coupon, writes a log, and returns a short JSON the website can display. The shopper sees a price, a badge, a coupon, a few reason codes, and a `decision_id`. They never see the model’s private numbers (how sure we were, which model version, the propensity). Those stay in the log for science and audit.

The **offline** half is the night shift. It is allowed to be slow. It reads yesterday’s logs, attaches “did they buy?”, rebuilds features as they were *at the moment of the decision*, trains, and estimates a new policy **before** that policy is allowed near live traffic. Some shoppers are held out at list price on purpose so we can still answer causal questions after the bandit has taken over the rest of the store.

**Resume line:** Built a FastAPI pricing system that chooses a constrained, personalized price with causal scoring and Thompson sampling, then evaluates challenger policies with off-policy evaluation (IPS/DR) before shadow and canary rollout.

---

## Words this README uses

A few terms show up everywhere. They are ordinary ideas with short names.

An **arm** is one legal price we might show, usually written `disc_0` (full list price), `disc_10` (10% off), and so on. A **guardrail** is a rule that deletes an arm before the model may want it — for example “this SKU is not discountable.” **μ (mu)** is the model’s guess of expected reward if we show that arm to this shopper (by default, expected margin). **σ (sigma)** is how unsure that guess is. A **propensity** is the probability that *this* policy would have chosen *this* arm in *this* context. We log it so we can later reweight history and score a policy we have not shipped yet. That scoring is **off-policy evaluation (OPE)**. **Holdout** means a slice of traffic that always sees list price, so we keep a clean comparison. **Fail closed** means “if we are not sure it is safe to personalize, show list price.” A **challenger** is a new model sitting in the registry; the **champion** is the one checkout is using today.

---

## What this system is built to answer

The **Science** tab in the lab is the same story as this section. The code is organized around five questions, not around a particular library.

The first question is causal: **what happens because we changed the price**, not “what happened next on the dashboard.” Conversion can go up after a discount for many reasons (a campaign ran the same week, only eager buyers got the code). Stage 4 therefore predicts expected reward as a function of context *and* action, μ(x, a). Holdout traffic never sees the bandit, so you can still compare “list price world” to “personalized world” after months of learning.

The second question is **how uncertainty should change the decision**. If two prices look similar but one has been tried a thousand times and the other is a deep discount on a brand-new guest, treating them as equal is how you overfit last week’s luck. The model returns a σ. Thompson sampling draws from that spread: unsure arms get a chance to be shown (that is how you learn); sure arms get used (that is how you earn). If we cannot even record the experiment, uncertainty is a reason to *stop* exploring, not a reason to randomize.

The third question is **when to exploit what we know versus experiment**. Most requests pick the arm that wins a Thompson draw. A small fraction (5% in the lab) pick uniformly so we do not starve rare arms. A request with `mode: exploit` skips that and takes the best mean — useful for a campaign that must not randomize. Stickiness remembers an offer for the same shopper and SKU so two page views are not two independent experiments. A frequency cap stops us from “learning” by discounting the same person twice a week.

The fourth question is **can we estimate a new policy before we fully deploy it**. Shipping a challenger to 100% of checkout “to see if it works” is an expensive experiment you cannot undo on orders already taken. OPE reweights old logs (IPS, SNIPS, doubly robust) and reports a confidence interval and an effective sample size. The gate only opens if that estimate beats the current policy *and* fairness and latency look acceptable. Then the new version logs in shadow, takes 1% of traffic, then more — or we keep the champion.

The fifth question is **how to optimize money while staying inside real constraints**. An unconstrained “optimal price” is a fiction. Inventory, vendor MAP, minimum margin, consent, bots, competitor bands, a daily discount budget, and a merchandiser kill switch all exist. The model only scores arms that survived those rules. List price is always left on the ladder so the system can fail closed.

Success is not a prettier number in a notebook. Success is lift you can measure in a controlled experiment, a loop that learns from its own prices, and a freeze that still works when legal calls at 2 a.m.

---

## Quick start

You need Python 3.11 or newer. Open a terminal in this folder (the one that contains `Dockerfile` and `pyproject.toml`). The first block creates a private Python environment, installs this package plus test tools, runs the tests so you know the brain works, and starts the website.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m uvicorn pricing_decision.api.app:app --host 127.0.0.1 --port 8080 --reload
```

`--reload` means the server restarts when you edit Python. Open **http://127.0.0.1:8080/** in a browser. That page *is* the product lab: you can price Maya on SKU-1234, walk each stage, run the night shift, and read the Azure / SageMaker runbooks.

If you want one decision without a browser, the CLI reads a JSON file and prints the result. `--explain` shows the internal scores (that is the same leak as the internal HTTP explain route — fine on your laptop, not for the public internet).

```bash
python -m pricing_decision.cli decide -f examples/request.json --explain
python -m pricing_decision.cli serve
```

The installable name is `pricing-decision-service`. The shortcut command is `pds`. Settings come from environment variables that start with `PDS_` — for example host, port, whether Kafka is on, where the log file lives, and the explore rate. You do not need those to start; defaults run the lab locally.

---

## The lab UI

The home page is a single HTML file, `src/pricing_decision/web/index.html`, served by FastAPI at `/`. There is no separate React build. The buttons across the top switch “pipelines.” Each pipeline has its own left-hand list of sections.

**Project** is a guided tour of folders and files: where FastAPI lives, what each stage file does, what `data/` is (generated, not source). Open it when you are lost. **Science** is the five questions above, written against this codebase. **Azure** is the Canada Central production runbook (how to host the same app, not a second brain). **SageMaker** is the same night shift on AWS, step by step. **Architecture** is the full loop around the brain: catalog, coupons, holdout, monitor, kill switch, use cases you can click. **Online PDS** is the live pipeline; pick Maya and SKU-1234 and press Run on each stage to see arms, scores, and the final price. **Offline learning** is the night shift on your laptop; seed some history, then walk ingest → join → OPE → gate.

The Azure, Project, Science, and SageMaker views are also plain URLs if you want them without the chrome: `/azure`, `/project`, `/science`, `/sagemaker`.

---

## Online pipeline (what happens on one checkout)

When a channel calls `POST /v1/price`, `PricingOrchestrator.decide()` in `orchestrator.py` walks a fixed sequence. Each step is a file under `src/pricing_decision/stages/`. Cloud hosting must not rewrite these files. Cloud only changes *adapters* under `services/` (where features are stored, where the catalog is read, where the log is sent).

**Stage 0 — Ingestion.** Is the request valid? Is the SKU real? Have we already answered this `decision_id` (a retry must not mint a second experiment)? We stamp version pins here (which policy, which causal model, which guardrail file) so a hot reload later cannot change a decision that is already in flight.

**Stage 1 — Preprocess.** Who is this person? Did they consent to personalization? We build the feature vector `x` (segment, sensitivity, churn risk, and so on). If consent is off, `x` stays generic — we do not quietly personalize. A missing `customer_id` is a guest.

**Stage 2 — Guardrails.** Before any model gets excited, we delete illegal prices. Below cost plus minimum margin, below MAP, SKU not discountable, stock too low, this shopper already used their discount quota, no consent, likely a bot, too far from a competitor, VIP fairness, daily budget exhausted, kill switch on. List price (`disc_0`) is always kept so we can still answer.

**Stage 3 — Candidates.** Whatever survived becomes the discrete ladder of arms. Holdout collapses that ladder to list price only.

**Stage 4 — Causal scoring.** For each surviving arm we predict expected reward and uncertainty. The lab uses a compact S-learner (a stand-in you could later swap for a heavier causal estimator). Reward can be margin, revenue, LTV, or a mix — that choice is a business decision, not a math constant.

**Stage 5 — Bandit.** Contextual Thompson sampling picks an arm and computes the propensity of that pick. That propensity is the most important number you will never show the customer. Without it, tonight’s OPE is guesswork.

**Stage 6 — Post-process.** Charm pricing (e.g. $44.99), issue a coupon that we must still honor after a policy change, and remember a sticky price so Maya does not see $45 then $40 ten seconds later.

**Stage 7 — Logging.** Write the experience tuple: context, candidates, chosen arm, propensity, version pins, whether this was a sticky replay. This must not sit on the critical path. If the log cannot be sent, we buffer and mark the row degraded.

**Stage 8 — Response.** Only client fields go on the wire.

**Stage 9 — Fallback.** If something is sick, we still return a price: last cached scores, segment defaults, ε-greedy, list price, then a static catalog price. Degraded rows are excluded from training so they do not teach the next model a lie.

**Stage 10 — Cache.** The live pins (policy id, causal model id, guardrail version) and hot reload.

The budget for the whole online path is a p99 under 100 ms. Default explore rate is 5%. Default propensity floor is 0.05 so later estimators never divide by zero.

If the decision log is down, buffer and **stop exploring**. Randomizing prices you cannot record is not science; it is noise.

---

## Offline pipeline (what happens tonight)

Checkout cannot wait for training. `offline/pipeline.py` is the conductor for the slow path. On a laptop the “lake” is JSONL files under `data/lake/`. The online service appends to `data/log_buffer/decisions.jsonl`. The registry is `data/registry/models.json`. In Azure those become Event Hubs, ADLS, and Azure ML. On AWS they become Kinesis or MSK, S3, and SageMaker. The Python stages stay the same.

**Ingest** copies live logs (and optional seeded history) into the lake once per `decision_id`. Duplicates would pretend we had more data than we do.

**Join** attaches outcomes (purchase, refund, return) to the decision that caused them. The key is `decision_id`, not customer id. Joining only on the person mixes two different prices shown on two different days. A reward window (about seven days) waits for a late purchase and nets out refunds. Rows still too new to judge are censored, not treated as “no purchase.”

**Backfill** rebuilds features as they were at the decision timestamp. Training on “whatever the profile is tonight” invents effects the price never caused.

**Causal** and **bandit** update the scorer and the policy on those honest rows.

**OPE** asks: if we had used the challenger on this old traffic, what would expected reward have been? IPS reweights by new-policy-probability / old-propensity. SNIPS stabilizes those weights. Doubly robust mixes the causal model’s guess with a correction so one bad piece cannot take the whole estimate. A bootstrap interval and **effective sample size** tell you whether the number is a measurement or a rumor. Rows without a propensity never enter.

**Fairness** and **drift** look at segment price gaps and whether the mix of propensities has shifted (PSI). Protected attributes used for audit must never sit inside the feature vector the model sees.

**Registry** stores the artifact. **Gate** is the adult: register as Production and start a canary only if OPE, ESS, fairness, and latency pass; otherwise keep the champion. **Rollout** is shadow (log, do not serve) then 1%, 5%, 25%, 100%, with a one-command rollback if live metrics go bad.

Open the Offline learning tab, seed about 80 decisions, and walk the stages in order. That is the same DAG SageMaker will run later.

---

## HTTP API

All HTTP lives in `src/pricing_decision/api/app.py`. `create_app()` builds the application; the module-level `app` is what uvicorn and Docker start. Port 8080 is the default.

`GET /` is the lab. `GET /health` is what a load balancer should ping. `GET /docs` is FastAPI’s own Swagger page.

`POST /v1/price` is the public contract. Web, app, and partners send shopper, SKU, cart, channel. They get only display fields. `POST /v1/price:explain` is the same decision with the guts attached (arms, scores, propensity, timings). It is for the lab and for internal debug. In production it must not face the internet.

`POST /v1/price:batch` is the campaign path (email, ads): same `decide()` contract, same logging, chunks of customers rather than one click. `POST /v1/outcomes` is how checkout tells us someone bought or refunded; the body must carry the `decision_id` from the price response. `GET /v1/decisions/{id}` is what a customer-service agent uses to explain a price without seeing model internals.

`GET` and `POST /v1/control` flip the kill switch, merchandiser freeze, and discount budget without a new image. Offer lookup and redeem are the coupon ledger: a code already shown is a promise. `POST /v1/admin/reload` refreshes version pins.

A typical request looks like `examples/request.json`: customer, session, SKU, cart value, channel, device, geo, timestamp. A typical response has `price`, `currency`, `discount_pct`, `badge`, `coupon_code`, `reason_codes`, `decision_id`, `expires_at`. If you see propensity on that response, something is wrong.

---

## Demo catalog

The lab is not an empty API. `configs/catalog.yaml` ships a small store so every button has someone to price.

Maya (`c_maya` or the older id `c_91823`) on `SKU-1234` is the happy path: a returning shopper, list price $50, discounts allowed if guardrails agree. A VIP profile sees a narrower ladder (you do not dump 30% on someone who would have paid full price). An at-risk profile can see deeper discounts *if* the rules still allow it. A no-consent profile must not get a personalized cut. `SKU-LOW` has so little stock that discounts are blocked (you do not learn by emptying a warehouse). `SKU-LOCKED` is not discountable at all.

If you omit `customer_id`, the service treats the caller as a **guest** and keeps personalization shallow. If you send a SKU that does not exist, you get **404** — we do not invent a product.

The Architecture tab’s use cases (kill switch, sticky twice, budget cap, holdout, batch) are the same catalog with pre-filled payloads from `configs/use_cases.yaml`.

---

## Folder map

Everything you maintain sits next to this README.

`pyproject.toml` tells Python this is a package, which libraries to install, and how to run pytest. `Dockerfile` packages the same FastAPI process for Azure Container Apps, AWS ECS, or a SageMaker job. `configs/` is the rulebook the running process reads (change a YAML, not a function, to add a SKU or flip a pin).

`src/pricing_decision/` is the only Python package. `api/app.py` is FastAPI. `web/index.html` is the lab. `orchestrator.py` is the wiring of stages 0–10. `stages/` is the online pipeline. `services/` is the seam you swap for Redis, Cosmos, Event Hubs, and so on. `core/` is shared types (the request, the offer, the exceptions). `offline/` is the night shift. `cli.py` is `serve` and `decide`.

`data/` is **output**, not design. You can delete the JSONL files; the next run recreates them. Do not hand-edit a training file and expect the models to stay coherent. `tests/` is pytest. `docs/` is the long HTML runbooks the lab iframes. `infra/` is PowerShell for the first Azure deploy. `examples/request.json` is a legal price call.

Ignore `.venv`, `.pytest_cache`, and `*.egg-info`. They appear after install and are not the product.

When you move to the cloud, you change adapters, not stages: feature store → Redis or ElastiCache; catalog / identity / coupons → Cosmos or DynamoDB; control plane → App Configuration or AWS AppConfig; logger → Event Hubs, MSK, or Kinesis; lake → ADLS or S3; registry → Azure ML or SageMaker Model Registry.

---

## Config

YAML under `configs/` is how merchandising and science change behavior without a deploy of new Python.

`catalog.yaml` is the demo store. `guardrails.yaml` is the legal and economic fences (MAP, margin, frequency, inventory, fairness). `ladders.yaml` is which discount steps each segment may even see. `features.yaml` is the contract for `x`: names, defaults, how long a cached feature may live. `control_plane.yaml` is the human override bus: kill switch, freeze, how long a sticky price lasts, the daily discount budget. `versions.yaml` names the current policy, causal model, and guardrail version so a log row is attributable. `segments.yaml` names shopper types.

`stages.yaml` and `offline_stages.yaml` are the words the lab shows next to each left-nav button. `use_cases.yaml` and `architecture.yaml` feed the Architecture tab. The `azure_*.yaml`, `science.yaml`, `sagemaker.yaml`, and `project_map.yaml` files are only navigation for those HTML runbooks.

Pins attach at ingestion. Reloading models in the middle of a request cannot rewrite a decision that already started.

---

## Azure (how this becomes production in Canada)

The **Azure** tab is a full implementation runbook, not a slide. The idea is: same FastAPI image, adapters pointed at managed services, **Canada Central** so personal and decision data stay in Canada (PIPEDA). Canada East is for disaster recovery later, not for cheaper training.

A public channel still posts `/v1/price`. Front Door and a WAF absorb bots (you do not want the bandit “learning” from scrapers). API Management exposes the public price route and keeps explain, control, and admin internal. Container Apps runs this container with revisions so 1% of traffic can try a new pin. Redis is the millisecond cache for features and sticky prices. Cosmos is the cabinet of record for catalog, identity, coupons, and CS lookup. App Configuration is the kill switch that must take effect on the next request. Event Hubs (Kafka protocol) carries decisions and outcomes; capture lands in ADLS. Azure ML runs the night shift. App Insights pages you if p99 or logging completeness goes bad.

Do not start on AKS or use Service Bus as the decision log. Service Bus is a command queue; this telemetry must never drop a propensity.

---

## SageMaker (how the night shift runs on AWS)

The **SageMaker** tab is step-by-step CLI. SageMaker is **not** the website. Shoppers still hit FastAPI on ECS or Container Apps. SageMaker reads the lake, trains, evaluates, and may register a challenger.

You create an S3 bucket in **`ca-central-1`** with bronze / silver / gold prefixes (the same idea as `data/lake`). An IAM role — not your laptop access key — is what jobs assume. You push this repo’s Docker image to ECR and run Processing jobs for ingest, join, backfill, and OPE, and small CPU Training jobs for causal and bandit. The Model Registry stores a package that stays Pending unless the same gate you already have says yes. Approved pins go back to FastAPI as a shadow then a canary.

Do not wrap `/v1/price` in a SageMaker real-time endpoint on day one. Do not train in `us-east-1` because the machine looks cheaper. Do not treat a job status of Completed as permission to ship; Completed only means the process exited.

If you host the *online* path on AWS as well, the adapters are ElastiCache, DynamoDB, AppConfig, MSK or Kinesis, and S3 — same rule: change `services/` and `offline/lake.py`, not the bandit.

---

## Tests

From this folder, `pytest` should stay green after you change a stage. The tests walk ingestion, preprocess, guardrails and candidates, causal and bandit, the safe response and the log, the lab’s “run this stage” API, the offline pipeline, and they check that the Architecture, Azure, Project, Science, and SageMaker pages still exist.

When you add tests that need a real cloud account, mark them so they skip unless `PDS_ENV` starts with `azure` or `aws`. Unit tests must keep using in-memory fakes so a laptop without credentials still proves the brain.

---

## What not to do

Do not rewrite the causal or bandit stages so they “look like” Azure or SageMaker. Do not train inside the online container (checkout will miss its latency budget and you will couple serving to a job that can fail). Do not put propensity or model ids on the public price response. Do not join purchases only on customer id. Do not keep exploring when the log is incomplete. Do not move shopper data to a cheaper region. Do not ship a model because a training job turned green.

The system should become better at operating the business because it has operated the business. That is why every live decision is logged with a propensity, and why a challenger can be refused.

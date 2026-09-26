from pathlib import Path

SECTIONS = {}

SECTIONS["how"] = r'''<section class="card" id="how">
  <p class="phase">Start here</p>
  <h2>How to use this file</h2>
  <p>This is the implementation runbook for this repository, not a generic Azure brochure. Keep it open beside PowerShell. Check a box when the work is actually done; progress stays in this browser. You will first put the same FastAPI lab onto Container Apps, then point the local stand-ins at Redis, Cosmos, Event Hubs, ADLS, and Azure ML. The stage contract does not change: ingest, guardrails, causal, bandit, log.</p>
  <p>On the laptop you need a development subscription where you have Contributor, Azure CLI after <code>az login</code> and <code>az account set</code>, Docker Desktop so <code>docker version</code> works, and the Python 3.11 environment this repo already uses. From the Pricing folder, <code>pip install -e ".[dev]"</code> then <code>pytest</code> should still report the same passing suite before you spend anything in Azure.</p>
  <label class="step"><input type="checkbox" data-k="need-az" /><span>Azure subscription you can create resources in (Contributor). Prefer a <b>dev</b> subscription first.</span></label>
  <label class="step"><input type="checkbox" data-k="need-cli" /><span>Install <a href="https://learn.microsoft.com/cli/azure/install-azure-cli">Azure CLI</a>, then <code>az login</code> and <code>az account set --subscription "&lt;name-or-id&gt;"</code>.</span></label>
  <label class="step"><input type="checkbox" data-k="need-docker" /><span>Install Docker Desktop and confirm <code>docker version</code> works.</span></label>
  <label class="step"><input type="checkbox" data-k="need-py" /><span>Python 3.11+ already used by this repo. From the Pricing folder: <code>pip install -e ".[dev]"</code> then <code>pytest</code> (should be 33 passed).</span></label>
  <p>Region is Canada Central so customer features, decisions, and rewards stay in Canada under PIPEDA. Canada East is for disaster recovery later. Do not put personal data in East US because it looks cheaper.</p>
</section>'''

SECTIONS["map"] = r'''<section class="card" id="map">
  <p class="phase">Architecture</p>
  <h2>1. What this project becomes on Azure</h2>
  <p>Every local piece has one production home. Keep this picture in mind while you build; it is the target, not a catalog of extras. A shopper on web, app, email, a till, or a partner never talks to Python. The call arrives at Front Door, which terminates TLS, picks a Canada POP, and should absorb bots so the bandit does not waste exploration on scrapers. API Management sits behind that door, rate-limits, authenticates, and exposes <code>POST /v1/price</code> while keeping explain and control on an internal product.</p>
  <div class="diagram">Channels (Web / App / Email / POS / Partners)
        │
        ▼
Azure Front Door + WAF          auth, bot, geo, TLS, Canada POP
        │
        ▼
API Management                  rate limit, product keys, /v1/price vs /explain
        │
        ▼
Container Apps  PDS             stages 0–10  (p99 &lt; 100ms)
   ├─ App Configuration         kill switch, freeze, versions, ladders
   ├─ Key Vault                 secrets, Event Hub conn, Redis key
   ├─ Redis                     online features, sticky price TTL
   ├─ Cosmos DB                 catalog, identity graph, offer ledger
   └─ Event Hubs (Kafka)        (x, a, p) decisions + outcomes
        │
        ▼
ADLS Gen2 (Delta)               lakehouse
        │
        ▼
Databricks / Fabric Spark       join, PIT backfill, OPE
        │
        ▼
Azure ML registry + gate        promote only if DR/OPE beats current
        │
        ▼
Container Apps revision split   shadow → 1% → 5% → 25% → 100%</div>
  <p>uvicorn on port 8080 becomes a Container App, and only later AKS if you outgrow revisions at something like ten thousand decisions a second. <code>gateway.py</code> becomes Front Door and APIM so bots and unauthenticated callers never reach Python. The in-memory feature store becomes Redis because a feature lookup has to finish in a millisecond or two. <code>catalog.yaml</code> and the identity dict become Cosmos DB so SKU economics, the customer graph, and the offer ledger survive a replica restart. <code>decisions.jsonl</code> becomes Event Hubs with Kafka and a schema registry so every decision is logged with a propensity. Local lake files become ADLS Gen2 Delta tables for point-in-time training and OPE. The numpy jobs under <code>offline/</code> become Azure ML, with Spark in Fabric or Databricks when the joins no longer fit one node. <code>models.json</code> becomes the Azure ML registry, with the same approval gate. <code>control_plane.yaml</code> becomes App Configuration so a kill switch does not wait for a new image. Sticky dicts and coupon lists become Redis TTLs plus a Cosmos ledger so an issued price is still honored. In-process metrics become App Insights. The lab UI stays the same app, on internal ingress only, because <code>/v1/price:explain</code> must not face the internet.</p>
</section>'''

SECTIONS["names"] = r'''<section class="card" id="names">
  <p class="phase">Phase 0</p>
  <h2>2. Set names (do this once)</h2>
  <p>Open PowerShell in the Pricing folder. Paste this block and keep the window open for every later step. Canada Central is the region. ACR, Key Vault, and storage names are globally unique, which is why a random suffix is appended; write the printed values down before you close the window.</p>
  <pre><button class="copy">Copy</button><code>$Location = "canadacentral"
$EnvName  = "dev"                          # later: test, prod
$Prefix   = "pds"
$Suffix   = Get-Random -Minimum 1000 -Maximum 9999
$RG       = "rg-$Prefix-$Location-$EnvName"
$ACR      = ($Prefix + "acr" + $EnvName + $Suffix).ToLower()   # globally unique
$ACA_ENV  = "cae-$Prefix-$EnvName"
$APP      = "ca-$Prefix-api"
$REDIS    = "redis-$Prefix-$EnvName-$Suffix"
$COSMOS   = "cosmos-$Prefix-$EnvName-$Suffix"
$EHNS     = "evh-$Prefix-$EnvName-$Suffix"
$STG      = ("st" + $Prefix + $EnvName + $Suffix).ToLower()    # storage: letters+numbers
$KV       = "kv-$Prefix-$EnvName-$Suffix"
$APPCS    = "appcs-$Prefix-$EnvName-$Suffix"
$LA       = "log-$Prefix-$EnvName"
$AI       = "appi-$Prefix-$EnvName"
$MLW      = "mlw-$Prefix-$EnvName-$Suffix"
Write-Host "RG=$RG ACR=$ACR STG=$STG KV=$KV"</code></pre>
  <label class="step"><input type="checkbox" data-k="p0-vars" /><span>Variables printed. Save them in a notepad — ACR, Key Vault, and storage names cannot be reused if you delete them carelessly.</span></label>
  <p>In development, keep the Container App at half a vCPU and a gigabyte of memory with one to three replicas. Redis can be Basic C0, Cosmos serverless, Event Hubs Standard with one throughput unit and Kafka enabled. Skip API Management and Front Door and use the Container Apps hostname. Production is a different envelope: a full vCPU and two gigabytes, three to thirty replicas in a zone-redundant environment; Redis Premium with TLS and a private endpoint; Cosmos autoscale with failover to Canada East; Event Hubs Premium with capture into ADLS; APIM Standard v2 or Premium on a VNet; Front Door Premium with the bot manager.</p>
</section>'''

SECTIONS["login"] = r'''<section class="card" id="login">
  <p class="phase">Phase 1</p>
  <h2>3. Login, resource group, register providers</h2>
  <p>Sign in so Azure knows which directory and subscription to bill. Create the resource group in Canada Central; everything later in this runbook lands inside it, and deleting the group is how you stop paying. Register the resource providers once per subscription. Registration is free and only means “this subscription is allowed to create these kinds of things.”</p>
  <pre><button class="copy">Copy</button><code>az login
az account show --query "{name:name, id:id, user:user.name}" -o table
az group create --name $RG --location $Location

az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.Cache
az provider register --namespace Microsoft.DocumentDB
az provider register --namespace Microsoft.EventHub
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.KeyVault
az provider register --namespace Microsoft.AppConfiguration
az provider register --namespace Microsoft.Insights
az provider register --namespace Microsoft.MachineLearningServices
az provider register --namespace Microsoft.OperationalInsights</code></pre>
  <label class="step"><input type="checkbox" data-k="p1-rg" /><span>Resource group exists: <code>az group show -n $RG --query location -o tsv</code> returns <code>canadacentral</code>.</span></label>
</section>'''

SECTIONS["redis"] = r'''<section class="card" id="redis">
  <p class="phase">Phase 5</p>
  <h2>7. Redis — online features + sticky prices</h2>
  <p>This replaces <code>FeatureStore</code> and <code>StickyPriceStore</code>. A feature GET should finish in well under two milliseconds. Create the cache with TLS only, then put the connection string in Key Vault rather than on the Container App as a raw environment secret.</p>
  <pre><button class="copy">Copy</button><code>az redis create -g $RG -n $REDIS -l $Location --sku Basic --vm-size C0 --enable-non-ssl-port false
$REDIS_HOST = az redis show -g $RG -n $REDIS --query hostName -o tsv
$REDIS_KEY  = az redis list-keys -g $RG -n $REDIS --query primaryKey -o tsv
az keyvault secret set --vault-name $KV --name redis-connection `
  --value "rediss://:$REDIS_KEY@$REDIS_HOST:6380/0"</code></pre>
  <p>Keys are short-lived and named so you can find them in a hurry. Feature vectors live at <code>feat:{customer_id}</code> with the TTL from <code>features.yaml</code>, often five minutes. A sticky offer is <code>sticky:{customer_id}:{sku}</code> for about thirty minutes. How often this shopper has already been discounted is <code>freq:{customer_id}:disc:30d</code>. The daily discount budget is an incrementing <code>budget:discount:yyyy-mm-dd</code> that expires after two days. In <code>services/feature_store.py</code> and <code>services/control_plane.py</code>, swap the in-memory dict for <code>redis.Redis.from_url(os.environ["REDIS_URL"])</code> and keep the same methods (<code>get</code>, <code>lookup</code>, <code>remember</code>) so <code>orchestrator.py</code> does not change.</p>
  <label class="step"><input type="checkbox" data-k="p5-redis" /><span>Two <code>POST /v1/price</code> with <code>"sticky": true</code> for Maya + SKU-1234 return the same price. Redis Browser / <code>redis-cli GET sticky:c_maya:SKU-1234</code> shows the key.</span></label>
</section>'''

SECTIONS["ml"] = r'''<section class="card" id="ml">
  <p class="phase">Phase 8</p>
  <h2>10. Offline learning on Azure ML + Spark</h2>
  <p>Do not train on the Container App. Nightly jobs map one-for-one onto <code>offline/pipeline.py</code>. Ingest turns Event Hub capture into Delta bronze on ADLS. Join matches decisions to outcomes on <code>decision_id</code> with a seven-day reward window net of refunds, and writes silver training rows. Backfill reconstructs features as of the decision timestamp, not “current.” Causal training is an Azure ML job (the numpy S-learner in this repo first, EconML later). The bandit job writes a policy artifact. OPE computes IPS, SNIPS, DR, a bootstrap interval, and effective sample size into <code>gold/ope</code>. The registry step registers a model only if the DR estimate of the new policy beats the current one by the threshold, ESS is healthy, the fairness gap is under five percent, and max PSI is under 0.2. The gate then opens a new Container Apps revision at zero traffic — shadow — before any shopper sees it.</p>
  <pre><button class="copy">Copy</button><code>az extension add -n ml
az ml workspace create -g $RG -n $MLW -l $Location --storage-account $STG

# First training job: reuse the Python you already have
# Create a job YAML (save as infra/train-causal.yml) then:
# az ml job create -g $RG -w $MLW -f infra/train-causal.yml</code></pre>
  <p>A minimal <code>infra/train-causal.yml</code> reuses the pipeline you already run locally:</p>
  <pre><button class="copy">Copy</button><code>$schema: https://azuremlschemas.azureedge.net/latest/commandJob.schema.json
command: python -c "from pricing_decision.offline.pipeline import OfflinePipeline; from pricing_decision.orchestrator import PricingOrchestrator; OfflinePipeline(PricingOrchestrator()).run('ol_ope', {'seed_n': 200})"
experiment_name: pds-offline
environment:
  image: mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04
  conda_file: ../conda.train.yml
compute: azureml:serverless
outputs:
  model:
    type: uri_folder</code></pre>
  <p>When a candidate clears the gate, copy a revision at zero percent, then move a percent, then five, twenty-five, and a hundred. If an App Insights alert fires, put the new revision back to zero. That is the same shadow-then-canary story as the lab, expressed as Container Apps traffic weights.</p>
  <pre><button class="copy">Copy</button><code># New revision, 0% traffic = shadow (logs, does not serve)
az containerapp revision copy -g $RG -n $APP --from-revision &lt;current&gt; --image "$ACR.azurecr.io/pds-api:v0.2.0"
az containerapp ingress traffic set -g $RG -n $APP --revision-weight &lt;old&gt;=100 &lt;new&gt;=0

# Canary
az containerapp ingress traffic set -g $RG -n $APP --revision-weight &lt;old&gt;=99 &lt;new&gt;=1
# then 5, 25, 100. Auto-rollback: if App Insights alert fires, set new=0.</code></pre>
  <label class="step"><input type="checkbox" data-k="p8-ml" /><span>One Azure ML job completes, a model appears in the registry tagged <code>policy_id</code> + <code>causal_model_id</code>, and OPE JSON is in <code>gold/ope/</code>.</span></label>
</section>'''

SECTIONS["edge"] = r'''<section class="card" id="edge">
  <p class="phase">Phase 9</p>
  <h2>11. Front Door + APIM (public edge)</h2>
  <p>Do this when a real channel will call pricing. Until then, the Container Apps hostname plus an IP restriction is enough. When you do put a door in front, split products the way <code>gateway.py</code> already thinks. Channels call <code>POST /v1/price</code> with a JWT or subscription key, about fifty requests per second per customer, and they never receive an explain body. CRM and email call <code>POST /v1/price:batch</code> with a managed identity and a larger payload limit. Checkout posts outcomes with a managed identity. CS tools look up <code>GET /v1/decisions/{id}</code> with Entra and a CS group. Explain, control, and admin are not on Front Door at all; they live on an internal APIM product.</p>
  <pre><button class="copy">Copy</button><code># APIM is billed even when idle. Use Developer SKU in dev, Standard v2 in prod.
az apim create -g $RG -n "apim-$Prefix-$EnvName-$Suffix" -l $Location --sku-name Developer --publisher-email you@company.com --publisher-name "Pricing"

# Front Door Premium: WAF bot manager + Canada anycast
# Portal is easier the first time: Create profile → origin group = APIM gateway hostname
# WAF: Bot manager + rate limit + geo allow CA/US if that is your market</code></pre>
  <label class="step"><input type="checkbox" data-k="p9-edge" /><span>Public <code>POST /v1/price</code> works with a subscription key. <code>/v1/price:explain</code> from the internet returns 404/401.</span></label>
</section>'''

SECTIONS["monitor"] = r'''<section class="card" id="monitor">
  <p class="phase">Phase 10</p>
  <h2>12. Monitor, fairness, rollback</h2>
  <p>A bandit you cannot measure is just random prices. Create Application Insights against the same Log Analytics workspace you attached to Container Apps, then pass the connection string into the app. Instrument FastAPI with OpenTelemetry toward Azure Monitor. You can keep the in-process Prometheus counters for the lab, but App Insights is what production paging will use.</p>
  <pre><button class="copy">Copy</button><code>az monitor app-insights component create -g $RG -l $Location -a $AI --workspace $LA
$AI_CONN = az monitor app-insights component show -g $RG -a $AI --query connectionString -o tsv
az containerapp update -g $RG -n $APP --set-env-vars "APPLICATIONINSIGHTS_CONNECTION_STRING=$AI_CONN"</code></pre>
  <p>Before you take the bandit live, those alerts have to exist with a named owner. If p99 of <code>/v1/price</code> sits above 100 ms for five minutes, page on-call and scale replicas. If availability drops under 99.9 percent or 5xx crosses one percent, put all traffic on the last known-good revision. If Event Hub ingress lags request count by more than a tenth of a percent, force exploit so you stop exploring into an incomplete log. If rolling hourly revenue falls far below predicted value, freeze discounts and investigate. If propensity PSI crosses 0.2, stop exploring and retrain. If a protected-group price gap exceeds five percent, turn the kill switch on. If the kill switch flag cannot be read, fail closed to list price.</p>
  <pre><button class="copy">Copy</button><code># Example: 5xx → rollback traffic (fill IDs after first revision)
az monitor metrics alert create -g $RG -n pds-5xx `
  --scopes $(az containerapp show -g $RG -n $APP --query id -o tsv) `
  --condition "avg Requests > 0" `
  --description "Replace condition with Http5xx when the metric namespace is visible" `
  --action $(az monitor action-group create -g $RG -n ag-pds-oncall --short-name pds --action email you you@company.com --query id -o tsv)</code></pre>
  <label class="step"><input type="checkbox" data-k="p10-mon" /><span>App Insights live metrics show POST /v1/price. You have an action group email. You documented the revision rollback command in your on-call notes.</span></label>
</section>'''

SECTIONS["code"] = r'''<section class="card" id="code">
  <p class="phase">Code you must change</p>
  <h2>14. Adapter swap list (keep stage files)</h2>
  <p>Do not rewrite <code>stages/stage4_causal.py</code> or the bandit to “be Azure.” Swap adapters only. <code>config.py</code> grows settings for App Configuration, Redis, Cosmos, Kafka, and Key Vault. <code>services/feature_store.py</code> becomes Redis GET and SET of JSON. <code>services/control_plane.py</code> reads App Configuration flags, increments the Redis discount budget, and stores sticky prices. Catalog, identity, coupons, and decision lookup read Cosmos containers <code>catalog</code>, <code>customers</code>, <code>offers</code>, and <code>decisions</code>. <code>services/logger.py</code> produces to Event Hubs over Kafka and falls back to the local buffer. Outcomes go to <code>pricing.outcomes.v1</code>. The lake uses ADLS Delta. The registry uses the Azure ML SDK. Rollout talks to the Container Apps revision traffic API. <code>api/app.py</code> adds App Insights middleware and splits public routers from admin. Unit tests should still pass against in-memory fakes. Mark Azure integration tests so they skip unless <code>PDS_ENV</code> starts with <code>azure</code>.</p>
  <label class="step"><input type="checkbox" data-k="p14-adapters" /><span>Unit tests still pass with in-memory fakes. Add integration tests marked <code>@pytest.mark.azure</code> that skip unless <code>PDS_ENV</code> starts with <code>azure</code>.</span></label>
</section>'''

SECTIONS["privacy"] = r'''<section class="card" id="privacy">
  <p class="phase">Phase 12</p>
  <h2>15. PIPEDA / Law 25 / fairness (Canada)</h2>
  <p>Every store that holds shopper or decision data is created in Canada Central. Confirm it with <code>az resource list -g $RG --query "[].{n:name,l:location}"</code> before you call this production. Consent already exists in preprocess: if the flag is off, the service sends a generic feature vector. Protected attributes such as exact age, gender, or ethnicity may live in a locked Cosmos container for audit and must never enter the feature vector; Azure Policy can deny unexpected columns in the training Delta table. In production, Key Vault and the data plane sit behind private endpoints, and public networks on Cosmos, Redis, and Storage are off. Retention in <code>control_plane.yaml</code> is 400 days; set Event Hub and ADLS lifecycle to match, then purge. Microsoft Purview scans ADLS, classifies PII, and is how you show that bronze decisions are not a free-for-all.</p>
  <label class="step"><input type="checkbox" data-k="p12-privacy" /><span>Legal signed off: purpose of personalization, retention, kill switch, and “CS can explain a price by decision_id without model guts.”</span></label>
</section>'''

SECTIONS["cost"] = r'''<section class="card" id="cost">
  <p class="phase">Money</p>
  <h2>17. Cost sketch (Canada Central, 2026 ballpark)</h2>
  <p>These are order-of-magnitude numbers so you are not surprised on the invoice, not a quote from Microsoft. A development month of Container Apps, ACR, and Log Analytics is tens of dollars, Redis Basic another twenty, Cosmos serverless twenty to eighty, Event Hubs and ADLS thirty to sixty, and Azure ML jobs fifty to a hundred fifty if you remember to stop compute. Skip Front Door and APIM in development and the whole slice often lands between about 150 and 400 dollars a month. Production at serious traffic is a different conversation: hundreds for the app and logs, Redis Premium in the hundreds, Cosmos autoscale that can pass a thousand, Event Hubs and the lake a few hundred, ML and Spark from hundreds to a couple of thousand on a busy nightly, and APIM plus Front Door another thousand or two. At around ten thousand requests a second, plan on a few thousand to the high thousands a month, and put a named owner on the bill.</p>
  <p>Put a budget alert on the resource group on day one. A budget emails you; it does not always shut resources off.</p>
  <pre><button class="copy">Copy</button><code>az consumption budget create --budget-name pds-dev-cap --amount 400 --time-grain Monthly --category Cost --resource-group $RG --start-date (Get-Date -Format yyyy-MM-01)</code></pre>
  <label class="step"><input type="checkbox" data-k="p17-budget" /><span>Budget + email alert created. You know who pays the bill.</span></label>
</section>'''

SECTIONS["plan"] = r'''<section class="card" id="plan">
  <p class="phase">Calendar</p>
  <h2>18. Eight-week implementation plan</h2>
  <p>Week one is the lab on Container Apps and a GitHub Action that builds the image to ACR on every main push. Week two is Key Vault, the App Configuration kill switch, App Insights, and the split between public and admin routes. Week three is Redis: features, sticky prices, the frequency cap, and the discount budget. Week four is Cosmos: catalog, identity, the offer ledger, the YAML load, and CS lookup by <code>decision_id</code>.</p>
  <p>Week five is Event Hubs, ADLS capture, outcomes on the second hub, and a completeness dashboard. Week six is Spark join and backfill, the Azure ML causal and OPE job, the registry, and a shadow revision. Week seven is a one-percent canary with holdout still at ten percent of traffic so you can estimate causal effects, plus a fairness workbook. Week eight is Front Door and APIM, private endpoints, Purview, disaster recovery toward Canada East, and a game day with CS, legal, and merchandising: kill switch, Event Hub outage, Redis outage — and the service must still return a price.</p>
  <label class="step"><input type="checkbox" data-k="p18-plan" /><span>Dates on a calendar. Week 8 game-day scheduled with CS + legal + merchandising.</span></label>
</section>'''

SECTIONS["fallback"] = r'''<section class="card" id="fallback">
  <p class="phase">Failure</p>
  <h2>20. Azure fallbacks (same ladder as the lab)</h2>
  <p>Checkout still needs a price when a dependency is sick, so the ladder is the same one you already coded, just aimed at Azure names. If Redis is down, serve a segment-level default feature vector, mark the call degraded, and still return a price. If Cosmos is down, use the catalog warmed into replica memory at boot; if that is cold, fall back to a static list price. If the causal model times out, reuse last scores in Redis, or the rule-based ladder. If Event Hubs is down, write the local buffer (or a blob) and switch to exploit only so you do not explore into a log you cannot keep. If App Configuration cannot be read, fail closed when the last known flag was kill, otherwise use cached flags no older than a minute. If APIM or Front Door is unhealthy, origin probes fail over to a second Container Apps environment in Canada East in production.</p>
  <label class="step"><input type="checkbox" data-k="p20-fallback" /><span>Chaos: stop Redis in dev. <code>/v1/price</code> still 200 with a price and <code>degraded</code> on the explain endpoint.</span></label>
</section>'''

SECTIONS["done"] = r'''<section class="card" id="done">
  <p class="phase">Done when</p>
  <h2>21. Definition of done</h2>
  <p>You have implemented this project on Azure when a channel can <code>POST /v1/price</code> in Canada Central under a 100 ms p99 and receive only client fields, with no propensity on the wire; when every decision is in Event Hubs with propensity and version pins, and outcomes join within seven days; when kill switch, sticky TTL, and offer redeem work without a redeploy; when nightly OPE can block a bad model and a canary revision can roll back in one command; and when holdout traffic still exists so you can estimate causal effects, not only bandit regret.</p>
  <label class="step"><input type="checkbox" data-k="done-1" /><span>A channel can <code>POST /v1/price</code> in Canada Central, p99 &lt; 100 ms, and get only client fields (no propensity).</span></label>
  <label class="step"><input type="checkbox" data-k="done-2" /><span>Every decision is in Event Hubs with propensity + version pins; outcomes join within 7 days.</span></label>
  <label class="step"><input type="checkbox" data-k="done-3" /><span>Kill switch, sticky TTL, and offer redeem work without a redeploy.</span></label>
  <label class="step"><input type="checkbox" data-k="done-4" /><span>Nightly OPE can block a bad model; canary revisions can roll back in one command.</span></label>
  <label class="step"><input type="checkbox" data-k="done-5" /><span>Holdout traffic still exists so you can estimate causal effects, not only bandit regret.</span></label>
  <p>Start today with login, Docker, and Container Apps. Everything after that is swapping adapters. The pricing brain you already built stays the same. The files that support the first deploy are <code>Dockerfile</code>, <code>.dockerignore</code>, <code>infra/azure-up.ps1</code>, and this HTML runbook.</p>
</section>'''


def replace_section(html: str, sid: str, new: str) -> str:
    marker = f'<section class="card" id="{sid}">'
    start = html.find(marker)
    if start < 0:
        raise SystemExit(f"missing start {sid}")
    nxt = html.find('<section class="card"', start + 1)
    if nxt < 0:
        end = html.find("</article>")
    else:
        end = nxt
    return html[:start] + new.strip() + "\n\n" + html[end:]


html_path = Path("docs/azure-implementation.html")
html = html_path.read_text(encoding="utf-8")
for sid, body in SECTIONS.items():
    html = replace_section(html, sid, body)

# Soften the header subtitle and the components nav tagline stays in yaml
html = html.replace(
    "Canada Central · follow every checkbox · this file is the runbook",
    "Canada Central · a readable runbook, with commands where you need them",
)

html_path.write_text(html, encoding="utf-8")
print("replaced", list(SECTIONS))

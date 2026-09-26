from __future__ import annotations

from typing import Any

from pricing_decision.config import load_yaml


def system_stage() -> dict[str, Any]:
    arch = load_yaml("architecture.yaml")
    if not isinstance(arch, dict):
        arch = {}
    loops = arch.get("loops") or {}

    def pack(title: str, key: str) -> dict[str, str]:
        steps = loops.get(key) or []
        detail = " ".join(f"{i + 1}) {step}" for i, step in enumerate(steps))
        return {"title": title, "detail": detail}

    return {
        "id": "system",
        "number": None,
        "title": arch.get("title", "Full architecture"),
        "tagline": arch.get("tagline", ""),
        "about": arch.get("about", ""),
        "in_short": arch.get("in_short", ""),
        "try": arch.get("try", ""),
        "process": [
            pack("Online PDS — the hot path", "online"),
            pack("Offline learning — the night shift", "offline"),
            pack("Feedback loop — how models get back to checkout", "feedback"),
        ],
        "loops": loops,
    }


def azure_architecture() -> dict[str, Any]:
    raw = load_yaml("azure_architecture.yaml")
    return raw if isinstance(raw, dict) else {}


def azure_components() -> dict[str, Any]:
    raw = load_yaml("azure_components.yaml")
    return raw if isinstance(raw, dict) else {}


def azure_tabs() -> list[dict[str, Any]]:
    rows = load_yaml("azure_stages.yaml")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def project_tabs() -> list[dict[str, Any]]:
    rows = load_yaml("project_map.yaml")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def science_tabs() -> list[dict[str, Any]]:
    rows = load_yaml("science.yaml")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def sagemaker_tabs() -> list[dict[str, Any]]:
    rows = load_yaml("sagemaker.yaml")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def architecture_tabs() -> list[dict[str, Any]]:
    arch = load_yaml("architecture.yaml")
    if not isinstance(arch, dict):
        arch = {}
    system = system_stage()
    added = arch.get("added_vs_typical_brain_diagram") or []
    az = azure_architecture()
    return [
        {
            **system,
            "id": "arch_map",
            "title": "System map",
            "process": system["process"]
            + [
                {
                    "title": "What a brain-only diagram usually misses",
                    "detail": " ".join(f"{i + 1}) {item}." for i, item in enumerate(added)),
                }
            ],
        },
        {
            "id": "arch_azure",
            "number": None,
            "title": "Azure architecture",
            "tagline": az.get("tagline", "Same pricing service, hosted on Azure."),
            "about": az.get("about", ""),
            "in_short": az.get("in_short", ""),
            "try": az.get("try", "Open the Azure tab → Overview, then Architecture diagram, then CLI commands."),
            "process": [
                {
                    "title": "What happens on a live request",
                    "detail": "A channel calls POST /v1/price. Front Door and API Management sit in front so bots and unauthenticated clients never reach Python, and so /explain stays internal. Container Apps runs this FastAPI app from an image in ACR. App Configuration supplies the kill switch and version pins; Key Vault supplies secrets through a managed identity. Redis holds online features and sticky prices; Cosmos holds catalog, identity, and the coupon ledger. Guardrails, causal scores, and the bandit still run in-process. The client sees only price, coupon, reason codes, and decision_id.",
                },
                {
                    "title": "What happens after the price is shown",
                    "detail": "Event Hubs records context, action, propensity, and version pins without blocking checkout. Outcomes join later on decision_id. Capture writes bronze files to ADLS. Azure ML jobs join, backfill point-in-time features, train, and run OPE. A model is registered only if that estimate beats the current policy and fairness and drift are acceptable. A new revision is then shadowed and ramped, or rolled back from App Insights.",
                },
                {
                    "title": "What you should not substitute",
                    "detail": "Do not start on AKS or App Service. Do not use Service Bus for decision telemetry. Do not train on the online container. Do not put shopper or decision data outside Canada Central. Change adapters in services/, not the causal or bandit stages.",
                },
            ],
        },
        {
            "id": "arch_layers",
            "number": None,
            "title": "Layers",
            "tagline": "Every box that sits around the pricing brain.",
            "about": "These layers are first-class. Catalog, inventory, coupons, experiments, control plane, sticky prices, and CS lookup are not optional extras — without them the brain cannot stay legal, redeemable, or auditable.",
            "in_short": "Sixteen layers from channel to support. PDS is one of them.",
            "try": "Read the layer cards. Then run a use case that hits that layer (kill switch, sticky, campaign).",
            "process": [
                {"title": layer["title"], "detail": f"{layer['purpose']} Pieces: {', '.join(layer.get('pieces') or [])}."}
                for layer in arch.get("layers") or []
            ],
        },
        {
            "id": "arch_usecases",
            "number": None,
            "title": "Use cases",
            "tagline": "The same brain, ten different jobs.",
            "about": "PDP, cart recovery, win-back, bundles, upgrades, B2B, holdout, cold start, fairness, competitor, search match, batch campaigns, kill switch, sticky price, and budget cap all call decide() with a different trigger.",
            "in_short": "Pick a use case and run it. The payload is pre-filled from configs/use_cases.yaml.",
            "try": "Run UC13 kill switch (list price). Run UC14 sticky twice — same price. Run UC12 batch.",
            "process": [
                {"title": c["title"], "detail": f"Trigger: {c['trigger']} Reward: {c['reward']} Risk: {c['risk']}"}
                for c in (load_yaml("use_cases.yaml") or [])
                if isinstance(c, dict)
            ],
        },
        {
            "id": "arch_segments",
            "number": None,
            "title": "Segment playbooks",
            "tagline": "Bandit, causal, and guardrail emphasis per persona.",
            "about": "Guests explore under tight caps. VIP exploits quietly. At-risk wants deep win-back arms that MAP may still block. The playbook is config, not hard-coded ethics.",
            "in_short": "Same SKU, different segment → different ladder and policy stance.",
            "try": "Compare guest vs VIP vs at-risk on the price board after reading the playbooks.",
            "process": [
                {"title": name, "detail": f"Bandit: {spec.get('bandit')} Causal: {spec.get('causal')} Guardrail: {spec.get('guardrail')}"}
                for name, spec in (load_yaml("segments.yaml") or {}).items()
                if isinstance(spec, dict)
            ],
        },
        {
            "id": "arch_monitor",
            "number": None,
            "title": "Monitor & contracts",
            "tagline": "SLIs, fairness, drift, and the three contracts.",
            "about": "If logging completeness drops, OPE dies. If PSI on propensity exceeds 0.2, stop exploring blindly. If segment price gap exceeds 5%, the gate fails. Feature, decision, and reward contracts keep teams from silently changing Y.",
            "in_short": "Watch the live snapshot. Feature / decision / reward contracts are the API between teams.",
            "try": "Seed offline data, then open this tab. Check fairness gap and PSI.",
            "process": [
                {"title": "Feature contract", "detail": "Name, type, freshness TTL, owner. Training must use point-in-time values."},
                {"title": "Decision contract", "detail": "Context schema, action space, propensity in (0, 1]. Logged on every request."},
                {"title": "Reward contract", "detail": "Which event counts, delay window, net of refunds, one definition per training window."},
                {"title": "Offer contract", "detail": "Issued codes are honored after policy change. Sticky TTL keeps grid, PDP, and email aligned."},
            ],
        },
        {
            "id": "arch_gaps",
            "number": None,
            "title": "Gaps vs the original doc",
            "tagline": "What the brain-only architecture still left out.",
            "about": "The original write-up is complete on causal → bandit → OPE. Production pricing still needs a control plane, sticky prices, an offer ledger, batch campaigns, tax/FX, feature skew, action-space versions, multi-objective reward, and privacy retention. Those are now first-class layers.",
            "in_short": "Fourteen gaps. Each one is a layer, contract, or use case in this lab.",
            "try": "Read a gap, then run the matching use case (UC12–UC15) or open the control plane on Monitor.",
            "process": [
                {"title": g["title"], "detail": g["why"]}
                for g in (arch.get("gaps_in_original_doc") or [])
                if isinstance(g, dict)
            ],
        },
    ]

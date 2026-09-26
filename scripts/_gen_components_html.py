from pathlib import Path

import yaml

raw = yaml.safe_load(Path("configs/azure_components.yaml").read_text(encoding="utf-8"))
groups = {g["id"]: g for g in raw["groups"]}
by: dict[str, list] = {}
for c in raw["components"]:
    by.setdefault(c["group"], []).append(c)
badge = {"must": "Must have", "should": "Should have", "later": "Later / do not start here"}
out: list[str] = []
out.append('<section class="card" id="components">')
out.append('  <p class="phase">Bill of materials</p>')
out.append("  <h2>All Azure components for this project</h2>")
out.append(
    '  <p class="lead">This is the shopping list. <b>Must have</b> is required for a working pricing loop. '
    "<b>Should have</b> is required before public traffic. <b>Later</b> means do not start there. "
    "Put every data resource in Canada Central.</p>"
)
out.append(
    '  <div class="callout">Build in this order: foundation → hosting → config → Redis/Cosmos → '
    "Event Hubs/ADLS → Azure ML → Front Door/APIM → private network. Change code only in <code>services/</code>.</div>"
)
for gid, g in groups.items():
    items = by.get(gid, [])
    if not items:
        continue
    out.append(f"  <h3>{g['title']}</h3>")
    out.append(f'  <p class="lead">{g["about"]}</p>')
    for c in items:
        out.append('  <div class="box" style="margin:10px 0">')
        out.append(
            f'    <h4>{c["name"]} <span class="chip">{badge.get(c["required"], c["required"])}</span> '
            f'<span class="chip">week {c["week"]}</span></h4>'
        )
        out.append(f'    <div class="tool">{c["tool"]} · replaces: {c["replaces"]}</div>')
        out.append(f'    <p><b>Why:</b> {c["purpose"]}</p>')
        out.append(f'    <p><b>Dev SKU:</b> {c["sku_dev"]} · <b>Prod SKU:</b> {c["sku_prod"]}</p>')
        out.append(f'    <p><b>How:</b> {c["how"]}</p>')
        out.append(f'    <p><b>Watch out:</b> {c["pitfall"]}</p>')
        out.append("  </div>")
out.append(
    '  <label class="step"><input type="checkbox" data-k="all-components" />'
    "<span>I know week-1 must-haves versus week-8 edge/network, and I will not start on AKS or Service Bus.</span></label>"
)
out.append("</section>")
Path("_components_snip.html").write_text("\n".join(out) + "\n", encoding="utf-8")
print("ok", len(raw["components"]))

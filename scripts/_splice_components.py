from pathlib import Path

html_path = Path("docs/azure-implementation.html")
html = html_path.read_text(encoding="utf-8")
snip = Path("_components_snip.html").read_text(encoding="utf-8").strip() + "\n\n"
mark = '<section class="card" id="picture">'
if 'id="components"' in html:
    print("already inserted")
elif mark not in html:
    raise SystemExit("picture marker missing")
else:
    html_path.write_text(html.replace(mark, snip + mark, 1), encoding="utf-8")
    print("inserted ok")

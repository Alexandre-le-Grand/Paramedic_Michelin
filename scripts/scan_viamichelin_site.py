"""Scan le site ViaMichelin pour endpoints API actuels."""
import re
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
req = urllib.request.Request("https://www.viamichelin.fr/itineraires", headers={"User-Agent": UA})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")

for pat in ("vmrest", "bff.viamichelin", "iti.json", "graphql", "apir"):
    print(f"{pat}: {html.lower().count(pat)}")

scripts = re.findall(r'src="([^"]+\.js[^"]*)"', html)
print(f"scripts: {len(scripts)}")
for s in scripts[:10]:
    print(" ", s[:120])

# fetch first few JS bundles for vmrest mentions
checked = 0
for rel in scripts[:5]:
    if not rel.startswith("http"):
        url = "https://www.viamichelin.fr" + rel if rel.startswith("/") else rel
    else:
        url = rel
    try:
        js = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30
        ).read().decode("utf-8", errors="replace")
    except Exception as exc:
        print("skip", url, exc)
        continue
    checked += 1
    hits = [m.group(0) for m in re.finditer(r"https?://[a-z0-9./_-]+", js) if "michelin" in m.group(0)]
    uniq = sorted(set(hits))
    print(f"\n--- {url[:80]} ---")
    for h in uniq:
        if any(x in h for x in ("vmrest", "bff", "graphql", "apir", "iti")):
            print(" ", h)

print(f"\nChecked {checked} JS bundles")

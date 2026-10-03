"""Report entries normalize.reachable() can't reach in data/ (excluding internal/enemyOnly/unobtainable). -v lists them.
Run from the repo root. Tracks the source gaps behind #35 (hide every unreachable entry)."""
import json, sys
sys.path.insert(0, "scripts")
import normalize as N
L = lambda f: json.load(open(f"data/{f}.json"))
items, creatures, pieces = L("items"), L("creatures"), L("pieces")
got = N.reachable(items, creatures, pieces, L("recipes"), L("processing"), L("sources"), L("spawns"))
hid = lambda e: e.get("internal") or e.get("enemyOnly") or e.get("unobtainable")
for kind, coll, ids in zip(("items", "creatures", "pieces"), (items, creatures, pieces), got):
    left = sorted(e["id"] for e in coll if e["id"] not in ids and not hid(e))
    print(f"{kind}: {len(left)} of {sum(not hid(e) for e in coll)} unreached")
    if "-v" in sys.argv:
        print("  " + " ".join(left))

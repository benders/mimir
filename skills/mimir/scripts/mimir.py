#!/usr/bin/env python3
"""Answer Valheim questions from Mimir's Well (https://mimir.slackworks.com/), the site's own data (#84).

Standard library only, so it runs in Claude's code sandbox. The data is fetched from the live site (data/*.json and
search.json, cached for an hour) or read from a local build with --site DIR.

  mimir.py search iron sword          pages whose name or id has every word
  mimir.py show SwordIron             the whole entry, as JSON, and its page
  mimir.py get Iron                   every way to get it: crafting, smelting, gathering, drops, chests, traders
  mimir.py used-in Iron               what takes it: recipes, building pieces, smelters, bait
  mimir.py tree SwordIron             the requirements tree back to the first stage (the entry's `via`, recursively)
  mimir.py list items --type Shield   entries of a kind (items, creatures, pieces, effects), optionally by type/biome
  --up-to Swamp                       leave out what only becomes available after that stage (spoilers)
"""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SITE = "https://mimir.slackworks.com/"
STAGES = ["Meadows", "BlackForest", "Swamp", "Mountain", "Plains", "Mistlands", "AshLands", "DeepNorth", "PostGame"]
KINDS = {"items": "items", "creatures": "creatures", "pieces": "pieces", "effects": "status_effects"}
CACHE_TTL = 3600  # s


class Data:
    def __init__(self, site: str, up_to: int | None = None):
        self.site, self.up_to, self.files = site, up_to, {}
        self.local = not site.startswith(("http://", "https://"))
        if not self.local and not self.site.endswith("/"):
            self.site += "/"
        self.cache = Path(tempfile.gettempdir()) / "mimir-cache"

    def load(self, path: str):
        """A site file (data/items.json, search.json) as parsed JSON."""
        if path not in self.files:
            if self.local:
                text = (Path(self.site) / path).read_text(encoding="utf-8")
            else:
                f = self.cache / path.replace("/", "_")
                if f.exists() and time.time() - f.stat().st_mtime < CACHE_TTL:
                    text = f.read_text(encoding="utf-8")
                else:
                    req = urllib.request.Request(self.site + path, headers={"User-Agent": "mimir-skill"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        text = r.read().decode("utf-8")
                    self.cache.mkdir(exist_ok=True)
                    f.write_text(text, encoding="utf-8")
            self.files[path] = json.loads(text)
        return self.files[path]

    def data(self, name: str):
        return self.load(f"data/{name}.json")

    def by_id(self, name: str) -> dict:
        key = f"#{name}"
        if key not in self.files:
            self.files[key] = {e["id"]: e for e in self.data(name)}
        return self.files[key]

    def find(self, id_: str) -> tuple[str, dict] | None:
        """(data file, entry) for an id, trying items, creatures, pieces, effects, then the rest."""
        for name in ("items", "creatures", "pieces", "status_effects", "sources", "locations", "alt_biomes"):
            if id_ in self.by_id(name):
                return name, self.by_id(name)[id_]
        return None

    def resolve(self, word: str) -> str:
        """An id, given an id or a page name (case-insensitive); exits with suggestions when unknown."""
        if self.find(word):
            return word
        low = word.lower()
        for row in self.load("search.json"):
            if row[0].lower() == low or row[1].lower() == low:
                return row[1]
        hits = self.search(word.split())[:8]
        sys.exit(f"unknown id or name: {word}" + ("\ndid you mean: " + ", ".join(f"{h[0]} ({h[1]})" for h in hits)
                                                  if hits else ""))

    def name(self, id_: str) -> str:
        hit = self.find(id_)
        n = hit and hit[1].get("name")
        return f"{n} ({id_})" if n and n != id_ else id_

    def stage(self, id_: str) -> int | None:
        hit = self.find(id_)
        s = hit and hit[1].get("stage")
        return STAGES.index(s) if s in STAGES else None

    def visible(self, id_: str) -> bool:
        """Within --up-to: no stage (not settled) counts as the first, as on the site."""
        s = self.stage(id_)
        return self.up_to is None or (s or 0) <= self.up_to

    def page(self, id_: str) -> str | None:
        for row in self.load("search.json"):
            if row[1] == id_:
                return (self.site if not self.local else SITE) + row[2]
        return None

    def search(self, words: list[str]) -> list[list]:
        words = [w.lower() for w in words]
        rows = [r for r in self.load("search.json")
                if all(w in r[0].lower() or w in r[1].lower() for w in words)
                and (self.up_to is None or (r[5] or 0) <= self.up_to)]
        return sorted(rows, key=lambda r: (" ".join(words) != r[0].lower(), len(r[0]), r[0]))


def stage_name(s: int | None) -> str:
    return STAGES[s] if s is not None else "stage unknown"


def amount(r: dict) -> str:
    a = r.get("amount")
    return f"{a}× " if a and a != 1 else ""


def drop_items(table: dict | None) -> list[dict]:
    return (table or {}).get("items", [])


def where(src: dict) -> str:
    """Where a source is placed, briefly."""
    parts = []
    if src.get("biomes"):
        parts.append(", ".join(src["biomes"]))
    locs = sorted({l["location"] for l in src.get("locations", [])})
    if locs:
        parts.append("in " + ", ".join(locs[:6]) + (f" and {len(locs) - 6} more" if len(locs) > 6 else ""))
    return "; ".join(parts) or "not placed in the world"


def cmd_search(d: Data, a) -> None:
    rows = d.search(a.words)
    for r in rows[:a.limit]:
        print(f"{r[0]} | {r[1]} | {r[4]} | {stage_name(r[5])} | {SITE if d.local else d.site}{r[2]}")
    if len(rows) > a.limit:
        print(f"... {len(rows) - a.limit} more (--limit)")
    if not rows:
        print("no matches")


def cmd_show(d: Data, a) -> None:
    id_ = d.resolve(a.id)
    kind, e = d.find(id_)
    print(f"# {d.name(id_)}: {kind}, {stage_name(d.stage(id_))}")
    if e.get("unobtainable") or e.get("internal") or e.get("enemyOnly"):
        print("(not available to players: unobtainable, a creature attack or enemy-only gear)")
    if (url := d.page(id_)):
        print(url)
    print(json.dumps(e, indent=1, ensure_ascii=False))


def cmd_get(d: Data, a) -> None:
    id_ = d.resolve(a.id)
    out = []
    for r in d.data("recipes"):
        if r.get("item") == id_ and (r.get("enabled") or r.get("season")):
            cost = ", ".join(f"{amount(x)}{d.name(x['item'])}" for x in r.get("resources", []) if not x.get("upgrader"))
            at = f" at {d.name(r['station'])} level {r.get('stationLevel', 1)}" if r.get("station") else " by hand"
            more = " (upgrades only)" if r.get("upgradeOnly") else ""
            out.append(f"craft{more}{at}, {r.get('amount', 1)} per craft: {cost}")
    for p in d.data("processing"):
        if p.get("to") == id_:
            src = f"from {amount(p)}{d.name(p['from'])}" if p.get("from") else ""
            fuel = f", fuel {d.name(p['fuel'])}" if p.get("fuel") else ""
            out.append(f"{p['kind']} at {d.name(p['station'])} {src}{fuel}, {p.get('time', '?')} s")
    found = {}  # (how, source name) -> the sources: copies of one object (Ancient Pot variants) as one line
    for s in d.data("sources"):
        k, hit = s["kind"], None
        pick = s.get("pickable") or {}
        if pick.get("item") == id_ or any(o.get("item") == id_ for o in pick.get("oneOf", [])):
            hit = "pick up"
        elif k == "fishing" and s["id"] == id_:
            hit = "fish, bait " + ", ".join(d.name(b["item"]) for b in s.get("baits", []))
        elif k == "trader":
            for x in s.get("sells", []):
                if x["item"] == id_:
                    hit = f"buy for {x['price']} coins" + (f" (after {x['requiredKey']})" if x.get("requiredKey") else "")
        elif any(x.get("item") == id_ for x in drop_items(s.get("drops"))) or s.get("becomes") == id_:
            hit = {"container": "loot chest", "rock": "mine", "tree": "chop", "log": "chop"}.get(k, "break")
        if hit and (s.get("biomes") or s.get("locations") or s.get("becomes") or k == "trader"):  # placed only
            found.setdefault((hit, s.get("name") or s["id"]), []).append(s)
    for (hit, name), ss in found.items():
        merged = {"biomes": sorted({b for s in ss for b in s.get("biomes", [])}),
                  "locations": [l for s in ss for l in s.get("locations", [])]}
        ids = ", ".join(s["id"] for s in ss[:3]) + (", ..." if len(ss) > 3 else "")
        out.append(f"{hit}: {name} [{ids}] — {where(merged) if merged['biomes'] or merged['locations'] else 'grows from a placed object'}")
    for sp in d.data("spawns"):
        if sp["creature"] == id_:
            at = sp.get("location") or sp.get("parent") or sp.get("item") or ", ".join(sp.get("biomes", []))
            cond = [f"{k} {sp[k]}" for k in ("requiredGlobalKey", "requiredEvent", "altBiome") if sp.get(k)]
            out.append(f"spawn ({sp['source']}): {at}" + (f" ({', '.join(cond)})" if cond else ""))
    for c in d.data("creatures"):
        for x in c.get("drops", []):
            if x["item"] == id_ and d.visible(c["id"]):
                out.append(f"drop: {d.name(c['id'])}, {round(x.get('chance', 1) * 100, 1)}%, {x.get('min', 1)}-{x.get('max', 1)}")
    for p in d.data("pieces"):
        if (p.get("produces") or {}).get("item") == id_:
            out.append(f"produced by {d.name(p['id'])}")
    print(f"# How to get {d.name(id_)} ({stage_name(d.stage(id_))})")
    print("\n".join(f"- {o}" for o in out) or "- nothing gives it")
    hit = d.find(id_)
    if hit and hit[1].get("via"):
        print(f"earliest way (via): {json.dumps(hit[1]['via'], ensure_ascii=False)}")


def cmd_used_in(d: Data, a) -> None:
    id_ = d.resolve(a.id)
    out = []
    for r in d.data("recipes"):
        for x in r.get("resources", []):
            if x["item"] == id_ and r.get("item") and (r.get("enabled") or r.get("season")) and d.visible(r["item"]):
                out.append(f"recipe: {d.name(r['item'])}, {x.get('amount', 1)}" +
                           (f" (+{x['perLevel']} per quality level)" if x.get("perLevel") else ""))
        if r.get("station") == id_ and r.get("item") and d.visible(r["item"]):
            out.append(f"crafts: {d.name(r['item'])} (station level {r.get('stationLevel', 1)})")
    for p in d.data("pieces"):
        if (p.get("enabled") or p.get("season")) and d.visible(p["id"]):
            for x in p.get("resources", []):
                if x["item"] == id_:
                    out.append(f"build: {d.name(p['id'])}, {x.get('amount', 1)}")
            if id_ in p.get("tools", []):
                out.append(f"builds: {d.name(p['id'])}")
    for p in d.data("processing"):
        if id_ in (p.get("from"), p.get("fuel")) and d.visible(p["to"]):
            role = "input" if p.get("from") == id_ else "fuel"
            out.append(f"{p['kind']} {role}: {d.name(p['to'])} at {d.name(p['station'])}")
    for s in d.data("sources"):
        if any(b["item"] == id_ for b in s.get("baits", [])):
            out.append(f"bait for {s.get('name') or s['id']}")
    print(f"# {d.name(id_)} is used in")
    print("\n".join(f"- {o}" for o in out) or "- nothing")


def cmd_tree(d: Data, a) -> None:
    seen = set()

    def walk(id_: str, prefix: str, depth: int) -> None:
        hit = d.find(id_)
        e = hit[1] if hit else {}
        via = e.get("via") or {}
        how = " ".join(x for x in (via.get("how"), via.get("from")) if x)
        line = f"{prefix}{d.name(id_)} · {stage_name(d.stage(id_))}" + (f" · {how}" if how else "")
        if id_ in seen and via.get("needs"):
            print(line + " (see above)")
            return
        if via.get("biomes"):
            line += " in " + ", ".join(via["biomes"])
        print(line)
        seen.add(id_)
        if depth < a.depth:
            for n in via.get("needs", []):
                ref = n.get("item") or n.get("piece") or n.get("creature")
                walk(ref, "  " * (depth + 1) + "- " + amount(n), depth + 1)

    walk(d.resolve(a.id), "", 0)


def cmd_list(d: Data, a) -> None:
    rows = []
    for e in d.data(KINDS[a.kind]):
        if e.get("unobtainable") or e.get("internal") or e.get("enemyOnly") or not d.visible(e["id"]):
            continue
        if a.type and a.type.lower() not in (e.get("type", "") + " " + " ".join(e.get("tags", []))).lower():
            continue
        if a.stage and (e.get("stage") or "").lower() != a.stage.lower():
            continue
        if a.biome and not any(a.biome.lower() == b.lower() for b in (e.get("via") or {}).get("biomes", [])):
            continue
        rows.append(e)
    for e in rows[:a.limit]:
        print(" | ".join(str(x) for x in (e.get("name", ""), e["id"], e.get("type") or e.get("faction") or "",
                                           e.get("stage", "stage unknown"))))
    print(f"{len(rows)} entries" + (f", first {a.limit} shown (--limit)" if len(rows) > a.limit else ""))


def stage_arg(s: str) -> int:
    low = s.replace(" ", "").replace("-", "").lower()
    for i, st in enumerate(STAGES):
        if st.lower() == low:
            return i
    raise argparse.ArgumentTypeError(f"stage must be one of {', '.join(STAGES)}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=os.environ.get("MIMIR_SITE", SITE), help="site URL or a local build directory")
    ap.add_argument("--up-to", type=stage_arg, help="hide what becomes available only after this stage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("words", nargs="+")
    p.add_argument("--limit", type=int, default=25)
    for c in ("show", "get", "used-in"):
        sub.add_parser(c).add_argument("id")
    p = sub.add_parser("tree")
    p.add_argument("id")
    p.add_argument("--depth", type=int, default=6)
    p = sub.add_parser("list")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("--type", help="item type or piece tag, e.g. Shield, Helmet, Food, Crafting")
    p.add_argument("--stage", help="only this stage")
    p.add_argument("--biome", help="creatures spawning in this biome")
    p.add_argument("--limit", type=int, default=100)
    a = ap.parse_args(argv)
    d = Data(a.site, a.up_to)
    {"search": cmd_search, "show": cmd_show, "get": cmd_get, "used-in": cmd_used_in, "tree": cmd_tree,
     "list": cmd_list}[a.cmd](d, a)


if __name__ == "__main__":
    main()

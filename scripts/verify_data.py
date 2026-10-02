#!/usr/bin/env python3
"""Verify normalized site data: counts, referential integrity, known vanilla content. Stdlib only.

    scripts/verify_data.py [data_dir] [icons_dir]    # default: data/ and .cache/dump/public/icons

Like verify.py, checks invariants rather than exact values so balance patches don't fail it.
Icons are checked only if the icons dir exists (they are generated, not committed).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
ICONS = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".cache/dump" / os.environ.get("MIMIR_BRANCH", "public") / "icons"

failures: list[str] = []


def check(cond: bool, msg: str) -> bool:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)
    return cond


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def dangling(what: str, refs: list, valid: set) -> None:
    bad = sorted({r for r in refs if r not in valid})
    check(not bad, f"{what}: all {len(refs)} references resolve" + (f" (missing: {bad[:10]})" if bad else ""))


def main() -> int:
    print(f"verifying {DATA}")
    meta = load("meta.json")
    print(f"  game {meta['gameVersion']}")
    for key, lo in {"items": 800, "recipes": 300, "creatures": 100, "spawns": 50, "pieces": 400,
                    "processing": 30, "sources": 100, "status_effects": 50}.items():
        n = meta["counts"].get(key, 0)
        check(n >= lo, f"{key}: {n} >= {lo}")
    unresolved = meta.get("unresolvedTokens", [])
    check(len(unresolved) < 50, f"unresolved localization tokens: {len(unresolved)} < 50 {unresolved[:10]}")

    items = {i["id"]: i for i in load("items.json")}
    recipes = load("recipes.json")
    creatures = {c["id"]: c for c in load("creatures.json")}
    pieces = {p["id"]: p for p in load("pieces.json")}
    procs = load("processing.json")
    sources = load("sources.json")
    effects = {e["id"]: e for e in load("status_effects.json")}
    spawns = load("spawns.json")

    # Referential integrity: everything a page links to must exist.
    drops = [d["item"] for c in creatures.values() for d in c.get("drops", [])]
    drops += [d["item"] for s in sources for d in (s.get("drops") or {}).get("items", [])]
    drops += [s["pickable"]["item"] for s in sources if "pickable" in s]
    dangling("recipe outputs", [r["item"] for r in recipes if "item" in r], set(items))
    dangling("recipe ingredients", [x["item"] for r in recipes for x in r.get("resources", [])], set(items))
    dangling("recipe stations", [r["station"] for r in recipes if "station" in r], set(pieces))
    dangling("piece ingredients", [x["item"] for p in pieces.values() for x in p.get("resources", [])], set(items))
    dangling("piece tools", [t for p in pieces.values() for t in p.get("tools", [])], set(items))
    dangling("drops", drops, set(items) | set(creatures))  # some creatures "drop" spawns (eggs hatching etc.)
    dangling("creature attacks", [a for c in creatures.values() for a in c.get("attacks", [])], set(items))
    dangling("processing items", [x for p in procs for x in (p["from"], p["to"])], set(items))
    dangling("processing stations", [p["station"] for p in procs], set(pieces))
    dangling("spawned creatures/fish", [s["creature"] for s in spawns], set(creatures) | set(items))
    dangling("item effects", [i[k] for i in items.values() for k in ("equipEffect", "consumeEffect") if k in i]
             + [i["set"]["effect"] for i in items.values() if "effect" in i.get("set", {})], set(effects))

    if ICONS.is_dir():
        have = {f.stem for f in ICONS.glob("*.png")}
        used = [x["icon"] for x in [*items.values(), *pieces.values(), *effects.values()] if "icon" in x]
        dangling(f"icons in {ICONS}", used, have)
        png = (ICONS / "SwordBronze.png").read_bytes()[:24]
        check(png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") >= 32, "SwordBronze.png is a real PNG icon")
    else:
        print(f"  skip  icons (no {ICONS})")

    # Known vanilla content.
    sword = items.get("SwordBronze", {})
    check((sword.get("name") or "").lower() == "bronze sword", "SwordBronze: English name")
    check(sword.get("damages", {}).get("slash", 0) > 0 and sword.get("icon") == "SwordBronze", "SwordBronze: damage + icon")
    r = next((r for r in recipes if r.get("item") == "SwordBronze"), {})
    check(r.get("station") == "forge" and any(x["item"] == "Bronze" for x in r.get("resources", [])), "SwordBronze: forge recipe with Bronze")
    troll = creatures.get("Troll", {})
    check(troll.get("health", 0) > 0 and any(d["item"] == "TrollHide" for d in troll.get("drops", [])), "Troll: health + TrollHide drop")
    check(any(s["creature"] == "Troll" and "BlackForest" in s.get("biomes", []) for s in spawns), "Troll spawns in BlackForest")
    check(creatures.get("Eikthyr", {}).get("boss") is True, "Eikthyr: boss")
    check("Hammer" in pieces.get("piece_workbench", {}).get("tools", []), "workbench built with Hammer")
    check(any(p["from"] == "CopperOre" and p["to"] == "Copper" for p in procs), "smelting CopperOre -> Copper")
    check(any(d["item"] == "CopperOre" for s in sources for d in (s.get("drops") or {}).get("items", [])), "CopperOre has a world source")
    mead = items.get("MeadHealthMinor", {}).get("consumeEffect")
    check(bool(mead) and bool(effects.get(mead, {}).get("stats")), "MeadHealthMinor: consume effect with stats")
    check(items.get("CookedMeat", {}).get("food", {}).get("health", 0) > 0, "CookedMeat: food values")

    print()
    if failures:
        print(f"VERIFY DATA FAILED: {len(failures)} check(s)")
        return 1
    print("VERIFY DATA PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

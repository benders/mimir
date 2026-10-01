#!/usr/bin/env python3
"""Verify a raw dump is complete and sane. Exit 0 = pass, 1 = fail. Stdlib only.

Checks are deliberately about invariants that hold across game patches (counts in a plausible
range, well-known vanilla content present with the right shape), not exact values, so a normal
balance patch never fails verification but a broken or partial dump always does.

    scripts/verify.py [dump_dir]      # default: .cache/dump/public/raw
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".cache/dump" / os.environ.get("MIMIR_BRANCH", "public") / "raw"

failures: list[str] = []


def check(cond: bool, msg: str) -> bool:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)
    return cond


def load(rel: str):
    return json.loads((DUMP / rel).read_text(encoding="utf-8"))


def component(prefab: dict, type_name: str) -> dict | None:
    return next((c["fields"] for c in prefab["components"] if c["type"] == type_name and "path" not in c), None)


def main() -> int:
    print(f"verifying {DUMP}")
    if not check((DUMP / "manifest.json").is_file(), "manifest.json present (dump completed)"):
        return 1
    check(not (DUMP / "error.txt").exists(), "no error.txt")

    m = load("manifest.json")
    c = m["counts"]
    print(f"  game {m['gameVersion']} (network {m['networkVersion']}), dumper {m['dumperVersion']}")
    check(bool(m["gameVersion"]), "gameVersion set")
    check(not m["warnings"], f"no dumper warnings {m['warnings'] or ''}")
    check(c["skippedFields"] == 0, "no fields skipped by serializer")
    for key, lo in {"prefabs": 3000, "items": 800, "recipes": 300, "statusEffects": 50, "translations": 3000}.items():
        check(c[key] >= lo, f"{key}: {c[key]} >= {lo}")

    prefab_files = list((DUMP / "prefabs").glob("*.json"))
    check(len(prefab_files) == c["prefabs"], f"prefab files ({len(prefab_files)}) match manifest")

    unsupported = 0
    for f in prefab_files:
        unsupported += f.read_text(encoding="utf-8").count('"$unsupported:')
    check(unsupported == 0, f"no unsupported field types (found {unsupported})")

    # Known vanilla content, chosen to span the game's systems.
    sword = load("prefabs/SwordBronze.json")
    shared = (component(sword, "ItemDrop") or {}).get("m_itemData", {}).get("m_shared", {})
    check(shared.get("m_name") == "$item_sword_bronze", "SwordBronze: ItemDrop shared data")
    check(shared.get("m_damages", {}).get("m_slash", 0) > 0, "SwordBronze: has slash damage")
    check(shared.get("m_maxQuality", 0) >= 2, "SwordBronze: upgradeable")

    recipes = {r["name"]: r["fields"] for r in load("recipes.json")}
    r = recipes.get("Recipe_SwordBronze", {})
    check(r.get("m_item", {}).get("$ref") == "SwordBronze", "Recipe_SwordBronze -> SwordBronze")
    check(r.get("m_craftingStation", {}).get("$ref") == "forge", "Recipe_SwordBronze at forge")
    check(any(x["m_resItem"]["$ref"] == "Bronze" for x in r.get("m_resources", [])), "Recipe_SwordBronze needs Bronze")

    troll = load("prefabs/Troll.json")
    hum = component(troll, "Humanoid") or {}
    check(hum.get("m_health", 0) > 0, "Troll: health")
    check("m_pierce" in hum.get("m_damageModifiers", {}), "Troll: damage modifiers")
    drops = (component(troll, "CharacterDrop") or {}).get("m_drops", [])
    check(any(d["m_prefab"]["$ref"] == "TrollHide" for d in drops), "Troll: drops TrollHide")

    eikthyr = component(load("prefabs/Eikthyr.json"), "Humanoid") or {}
    check(eikthyr.get("m_boss") is True, "Eikthyr: is a boss")

    spawns = load("world/SpawnSystemList.json")
    check(sum(len(s["fields"].get("m_spawners", [])) for s in spawns) > 50, "spawn lists populated")

    loc = load("localization/English.json")
    check((loc.get("item_sword_bronze") or "").lower() == "bronze sword", "localization: item_sword_bronze")
    check("enemy_troll" in loc, "localization: enemy_troll")

    print()
    if failures:
        print(f"VERIFY FAILED: {len(failures)} check(s)")
        return 1
    print("VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

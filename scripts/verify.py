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
    for key, lo in {"prefabs": 3000, "items": 800, "recipes": 300, "statusEffects": 50, "pieceTables": 3,
                    "translations": 3000}.items():
        check(c.get(key, 0) >= lo, f"{key}: {c.get(key, 0)} >= {lo}")

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
    locations = list((DUMP / "locations").glob("*.json"))
    check(len(locations) > 100, f"locations dumped ({len(locations)})")
    check(len(list((DUMP / "rooms").glob("*.json"))) > 100, "dungeon rooms dumped")
    check("Crypt" in load("room_themes.json"), "room themes table")
    bowls = [c["fields"] for c in load("locations/Eikthyrnir.json")["components"] if c["type"] == "OfferingBowl"]
    check(any((b.get("m_bossPrefab") or {}).get("$ref") == "Eikthyr" for b in bowls), "Eikthyrnir location: altar summons Eikthyr")

    # Seasons (plugin 0.4.0+)
    seasons = {g["name"]: g["fields"] for g in load("world/seasons.json")}
    for key in ("yule", "midsummer", "halloween"):
        hit = [f for n, f in seasons.items() if key in n.lower()]
        check(bool(hit), f"seasons: a group named *{key}*")
        if hit:
            f = hit[0]
            check(len(f.get("_startDate") or []) == 2 and len(f.get("_endDate") or []) == 2, f"seasons: {key} has start/end dates")
            check(bool(f.get("Pieces")) or bool(f.get("Recipes")), f"seasons: {key} has pieces or recipes")

    # Sub-prefabs: non-networked prefabs referenced from dumped data (plugin 0.4.0+)
    sub = DUMP / "subprefabs"
    check(sub.is_dir() and len(list(sub.glob("*.json"))) > 20, "subprefabs dumped")
    check((sub / "staff_skeleton_spawn.json").is_file() or (DUMP / "prefabs" / "staff_skeleton_spawn.json").is_file(),
          "staff_skeleton_spawn dumped (SpawnAbility)")

    # Network prefab instances in the location/room hierarchy (plugin 0.4.0+)
    def instance_hits(subdir: str, needle: str) -> int:
        return sum(needle in f.read_text() for f in (DUMP / subdir).glob("*.json"))
    check('"instances"' in (DUMP / "locations" / "Eikthyrnir.json").read_text(), "locations carry an instances list")
    check(instance_hits("rooms", '"prefab":"Pickable_MountainCaveRandom"') > 0,
          "frost cave rooms place Pickable_MountainCaveRandom")
    check(instance_hits("locations", '"prefab":"Spawner_Bjorn_sleeping"') + instance_hits("rooms", '"prefab":"Spawner_Bjorn_sleeping"') > 0,
          "some location/room places Spawner_Bjorn_sleeping")

    tables = {t["name"]: t["fields"] for t in load("piece_tables.json")}
    hammer = tables.get("_HammerPieceTable", {}).get("m_pieces") or []
    check(any(p and p.get("$ref") == "piece_workbench" for p in hammer), "hammer piece table has the workbench")
    defaults = {d["type"] for d in load("status_effect_defaults.json")}
    check({e["type"] for e in load("status_effects.json")} <= defaults, "defaults for every status effect type")

    loc = load("localization/English.json")
    check((loc.get("item_sword_bronze") or "").lower() == "bronze sword", "localization: item_sword_bronze")
    check("enemy_troll" in loc, "localization: enemy_troll")

    anims = DUMP / "anims/Player_animator.json"
    if check(anims.is_file(), "anims/Player_animator.json present (scripts/anims.sh)"):
        trig = load("anims/Player_animator.json")["triggers"]
        check(len(trig) >= 50, f"attack triggers: {len(trig)} >= 50")
        sword = [trig.get(f"swing_longsword{k}") for k in range(3)]
        check(all(sword), "attack triggers: swing_longsword0..2")
        check(all(t and t["exit"] and any(e[1] in ("Hit", "OnAttackTrigger") for e in t["events"]) for t in sword), "swing_longsword: exit, hit event")
        check(all(t and any(e[1] == "Chain" for e in t["events"]) for t in sword[:2]), "swing_longsword0..1: Chain")
        done = trig.get("reload_crossbow_done") or {}
        check(done.get("tag") == "minoraction_fast" and done.get("exit"), "reload_crossbow_done: minor action with exit")

    icons = DUMP.parent / "icons"
    if icons.is_dir():
        check(len(list(icons.glob("*.png"))) >= 1000, "icons extracted (>= 1000)")
        check((icons / "SwordBronze.png").is_file(), "icon SwordBronze.png")
    else:
        print(f"  skip  icons (no {icons})")

    print()
    if failures:
        print(f"VERIFY FAILED: {len(failures)} check(s)")
        return 1
    print("VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

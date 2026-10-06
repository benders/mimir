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
    drops += [x["item"] for s in sources for x in (s.get("pickable") or {}).get("oneOf", [s.get("pickable") or {}])
              if "item" in x]
    dangling("recipe outputs", [r["item"] for r in recipes if "item" in r], set(items))
    dangling("recipe ingredients", [x["item"] for r in recipes for x in r.get("resources", [])], set(items))
    dangling("recipe stations", [r["station"] for r in recipes if "station" in r], set(pieces))
    dangling("piece ingredients", [x["item"] for p in pieces.values() for x in p.get("resources", [])], set(items))
    dangling("piece tools", [t for p in pieces.values() for t in p.get("tools", [])], set(items))
    dangling("drops", drops, set(items) | set(creatures))  # some creatures "drop" spawns (eggs hatching etc.)
    dangling("creature attacks/equipment", [a for c in creatures.values() for k in ("attacks", "equipment")
                                            for a in c.get(k, [])], set(items))
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
    combo = sword.get("attack", {})
    check(len(combo.get("chain", [])) == 3 and 1.5 < combo.get("cycle", 0) < 4 and combo.get("lastChainMultiplier") == 2,
          "SwordBronze: 3-hit combo timing (anims)")
    bow, xbow = items.get("Bow", {}).get("attack", {}), items.get("CrossbowArbalest", {}).get("attack", {})
    check(bow.get("draw", 0) > 0 and bow.get("chain"), "Bow: draw time and release animation")
    check(xbow.get("reload", 0) > 0 and xbow.get("reloadDone", 0) > 0, "Arbalest: reload and reload-done times")
    untimed = sorted(i["id"] for i in items.values() if i.get("type") in ("OneHandedWeapon", "TwoHandedWeapon",
                     "TwoHandedWeaponLeft", "Bow") and not (i.get("internal") or i.get("enemyOnly") or i.get("unobtainable"))
                     and not (i.get("attack") or {}).get("chain"))
    check(not untimed, f"every obtainable weapon's primary attack has animation timing ({untimed[:10]})")
    r = next((r for r in recipes if r.get("item") == "SwordBronze"), {})
    check(r.get("station") == "forge" and any(x["item"] == "Bronze" for x in r.get("resources", [])), "SwordBronze: forge recipe with Bronze")
    troll = creatures.get("Troll", {})
    check(troll.get("health", 0) > 0 and any(d["item"] == "TrollHide" for d in troll.get("drops", [])), "Troll: health + TrollHide drop")
    check(any(s["creature"] == "Troll" and "BlackForest" in s.get("biomes", []) for s in spawns), "Troll spawns in BlackForest")
    def spawned(creature, source, **kw):
        return any(s["creature"] == creature and s.get("source") == source
                   and all(s.get(k) == v or v in (s.get(k) or []) for k, v in kw.items()) for s in spawns)
    check(spawned("Fenring_Cultist", "dungeon", biomes="Mountain"), "Cultist: Mountain cave dungeon")
    check(spawned("Bonemass", "location", biomes="Swamp"), "Bonemass: Swamp altar")
    check(spawned("Neck", "raid", event="army_eikthyr"), "Necks in the Eikthyr raid")
    check(spawned("Wolf_cub", "offspring", parent="Wolf"), "Wolf cub born from Wolf")
    check(spawned("FrozenKing_p2", "phase", parent="FrozenKing") and spawned("FrozenKing_p3", "phase", parent="FrozenKing_p2"),
          "Moder-king's phases: FrozenKing -> _p2 -> _p3")
    check(spawned("BlobFrost", "summon", item="BombBlob_Frost"), "Blob Bomb: Frost summons a Frost Blob")
    check(spawned("Troll_Summoned", "summon", item="StaffRedTroll") and spawned("Skeleton_Friendly", "summon", item="StaffSkeleton"),
          "staffs summon through their (non-networked) abilities")
    check(spawned("Mistile", "summon", parent="DvergerMage") and spawned("Aspect_Eikthyr", "phase", parent="FrozenKing"),
          "Dvergr mage's Mistiles; FrozenKing's death burst spawns the Eikthyr aspect")
    check(spawned("Bat_Swamp", "world", biomes="Swamp"), "alt biome spawns (Bat_Swamp)")
    check(spawned("FallenWarrior", "location", location="NorthMemorialPlace"), "memorial offering summons Fallen Warriors")
    check(spawned("TrollFrost", "world", biomes="DeepNorth"), "TrollFrost: spawner-placed world spawn")
    check(all(s.get("biomes") for s in spawns if s.get("source") not in ("offspring", "egg", "growup", "summon", "phase")),
          "every spawn has a biome")
    bosses = [c for c in creatures.values() if c.get("boss") and not c["id"].endswith(("_p2", "_p3"))]
    unplaced = sorted(c["id"] for c in bosses if not any(s["creature"] == c["id"] for s in spawns))
    check(unplaced == ["Hive", "TheHive"], f"every boss but the Queen's hives has a location (unplaced: {unplaced})")
    check(creatures.get("Eikthyr", {}).get("boss") is True, "Eikthyr: boss")
    check(creatures.get("Skeleton_Hildir", {}).get("name") == "Brenna" and creatures["Skeleton_Hildir"].get("named"),
          "Brenna: plain name, flagged named")
    tagged = [e["id"] for coll in (items, creatures, pieces) for e in coll.values()
              if "<" in (e.get("name") or "") + (e.get("description") or "")]
    check(not tagged, f"no rich-text tags in names or descriptions ({tagged[:5]})")
    check((pieces.get("piece_xmastree", {}).get("season") or {}).get("name") == "Yule", "Yule tree is seasonal (Yule)")
    check(pieces.get("piece_maypole", {}).get("season", {}).get("start") == [1, 6], "maypole season starts 1 Jun")
    check(next((r for r in recipes if r["id"] == "Recipe_HelmetMidsummerCrown"), {}).get("season", {}).get("name") == "Midsummer",
          "Midsummer crown recipe is seasonal")
    check("season" not in pieces.get("piece_workbench", {}), "workbench isn't seasonal")
    check("Hammer" in pieces.get("piece_workbench", {}).get("tools", []), "workbench built with Hammer")
    check(any(p["from"] == "CopperOre" and p["to"] == "Copper" for p in procs), "smelting CopperOre -> Copper")
    check(any(d["item"] == "CopperOre" for s in sources for d in (s.get("drops") or {}).get("items", [])), "CopperOre has a world source")
    src = {s["id"]: s for s in sources}
    check(src.get("LeviathanLava", {}).get("locations"), "LeviathanLava (a Flametal Ore deposit) is placed as a location")
    check("Meadows" in src.get("RaspberryBush", {}).get("biomes", []), "RaspberryBush grows in the Meadows")
    check(any(d["item"] == "FlametalOreNew" for d in src.get("LeviathanLava", {}).get("drops", {}).get("items", [])),
          "FlametalOreNew is mined from a placed deposit")
    check(pieces.get("TreasureChest_meadows", {}).get("locations") and pieces.get("fire_pit_haldor", {}).get("locations"),
          "loot chests and Haldor's fire pit are placed in locations")
    in_chest = {d["item"] for s in sources if s.get("kind") == "container" and s.get("locations")
                for d in s["drops"]["items"]}
    check({"Amber", "AmberPearl", "Ruby"} <= in_chest, "Amber, AmberPearl, Ruby are found in chests")
    fish = {s["id"]: s for s in sources if s.get("kind") == "fishing"}
    check(len(fish) >= 12 and all(f["baits"] and f["id"] in items for f in fish.values()), "fish: fishing sources with baits")
    check(fish.get("Fish1", {}).get("baits", [{}])[0].get("item") == "FishingBait" and "Meadows" in fish["Fish1"]["biomes"],
          "Fish1: caught with FishingBait in Meadows")
    check(any(d["item"] == "Ruby" for d in fish.get("Fish3", {}).get("drops", {}).get("items", [])), "Fish3 can carry a Ruby")
    shops = {s["id"]: s for s in sources if s.get("kind") == "trader"}
    sold = {t: {o["item"]: o for o in shops.get(t, {}).get("sells", [])} for t in ("Haldor", "Hildir", "BogWitch")}
    check(all(shops.get(t, {}).get("locations") for t in sold), "Haldor, Hildir and the Bog Witch stand in locations")
    check(sold["Haldor"].get("BeltStrength", {}).get("price", 0) > 0 and "Coins" in items, "Haldor sells Megingjord for coins")
    check({"FishingBait", "Thunderstone"} <= set(sold["Haldor"]) and "BarberKit" in sold["Hildir"]
          and "SpiceOceans" in sold["BogWitch"], "Haldor sells bait and thunderstones, Hildir the barber kit, the Bog Witch spices")
    check(any(o.get("requiredKey") for o in sold["Hildir"].values()), "Hildir's offers unlock with global keys")
    mc = next((s for s in sources if s["id"] == "Pickable_MountainCaveRandom"), {})
    check("WolfClaw" in {x["item"] for x in mc.get("pickable", {}).get("oneOf", [])} and mc.get("locations"),
          "WolfClaw: found in the frost cave treasure pile (PickableItem), placed in cave rooms")
    made = {p["produces"]["item"]: p for p in pieces.values() if p.get("produces")}
    check({"Honey", "Sap"} <= set(made) and made["Honey"]["produces"]["secPerUnit"] > 0
          and "Mistlands" in made["Sap"]["produces"].get("connectsTo", {}).get("biomes", []),
          "Beehive makes Honey, the Sap Extractor Sap (from a Mistlands root)")
    hive = next((s for s in sources if s["id"] == "Beehive"), {})
    check({d["item"] for d in hive.get("drops", {}).get("items", [])} == {"Honey", "QueenBee"}, "wild Beehive drops Honey and QueenBee")
    check(any(s["creature"] == "Hen" and s.get("source") == "growup" for s in spawns), "Hen grows up from the Chicken")
    mead = items.get("MeadHealthMinor", {}).get("consumeEffect")
    check(bool(mead) and bool(effects.get(mead, {}).get("stats")), "MeadHealthMinor: consume effect with stats")
    check(items.get("CookedMeat", {}).get("food", {}).get("health", 0) > 0, "CookedMeat: food values")
    fw = creatures.get("FallenWarrior", {})
    weapons = {"OneHandedWeapon", "TwoHandedWeapon", "TwoHandedWeaponLeft", "Bow", "Torch", "Tool"}
    check(all(items[a]["type"] in weapons for c in creatures.values() for a in c.get("attacks", [])),
          "creature attacks are weapons only (armor goes to equipment)")
    check("FW_HelmetBronze" in fw.get("equipment", []), "FallenWarrior: FW_HelmetBronze is equipment")
    check(all(items[x].get("enemyOnly") for x in ("FW_ArmorBronzeChest", "SP_ArmorBronzeChest", "SP_ArmorDress1"))
          and not items["ArmorBronzeChest"].get("enemyOnly"), "FW_/SP_ gear copies are enemyOnly, the real item isn't")
    check(not any(i.get("enemyOnly") for i in items.values() if any(r.get("item") == i["id"] for r in recipes)),
          "no craftable item is enemyOnly")
    check(len({json.dumps(p, sort_keys=True) for p in procs}) == len(procs), "processing: each conversion once")
    check(not any("armor" in i for i in items.values() if i["type"] == "Shield" and not i.get("internal")),
          "shields carry no armor")
    check("armor" in items["ArmorBronzeChest"] and not {"armor", "block", "skill"} & items["Wood"].keys(),
          "item stat fields kept only for the types that use them")
    check(any(h["kind"] == "area" for h in items["DvergerStaffNova"].get("hits", [])),
          "DvergerStaffNova: damage from its Aoe (hits)")
    check(any(h["kind"] == "area" for h in items["troll_groundslam"].get("hits", [])),
          "troll_groundslam: weapon spawnOnHit Aoe in hits")
    trinkets = [i for i in items.values() if i["type"] == "Trinket" and not i.get("unobtainable")]
    check(len(trinkets) >= 10 and all(i.get("adrenaline", {}).get("max", 0) > 0 and i["adrenaline"].get("effect") in effects
                                      for i in trinkets), f"{len(trinkets)} trinkets, each with max adrenaline and a known effect")
    check(items["TrinketBlackStamina"].get("adrenaline", {}).get("effect") == "TrinketBlackStamina",
          "TrinketBlackStamina fires its own effect when adrenaline is full")
    adr = load("player.json").get("adrenaline", {})
    check(len(adr.get("degen", [])) >= 2 and len(adr.get("degenDelay", [])) >= 2, "player.json: adrenaline decay curves")
    check(any(s.get("becomes") == "DvergrKeyFragment" and s.get("locations") for s in sources),
          "DvergrKeyFragment: placed blackmarble_altar_crystal breaks into it")
    hidden = {"Deer_White", "DvergerTest", "FrostWisp", "Hive", "TheHive", "IceSkates", "Larva", "TorchMist", "Sled",
              "SwordCheat", "CapeTest", "HealthUpgrade_GDKing", "Draugr_sleeping", "HildirKey_forestcrypt", "OLD_wood_roof"}
    every = {**items, **creatures, **pieces}
    check(all(every.get(x, {}).get("unobtainable") for x in hidden), "unreleased, test and unused content is unobtainable")
    # Known-obtainable vanilla content, one or more per kind of source, so a gap in reachable() can't hide real pages.
    obtainable = {
        "Wood", "Stone", "Hammer", "Coins", "Amber", "AmberPearl", "Ruby", "SilverNecklace", "FishRaw", "Fish1",
        "MeadHealthMinor", "BeltStrength", "Thunderstone", "Honey", "QueenBee", "Sap", "FlametalOreNew", "FlametalNew",
        "WolfClaw", "CrownJewel", "DvergrKeyFragment", "ChickenEgg", "AsksvinEgg", "HelmetMidsummerCrown", "HelmetYule",
        "TrophyEikthyr", "BlackMetal", "Eitr", "OrbFrostFire", "darkwood_beam_67",
        "Boar", "Eikthyr", "Troll", "Draugr", "Skeleton", "Leech", "Serpent", "Lox", "Hen", "Chicken", "DvergerMage",
        "Troll_Summoned", "Bat_Swamp", "Aspect_Eikthyr", "FrozenKing", "FallenWarrior", "Skeleton_Hildir",
        "piece_workbench", "forge", "portal_wood", "piece_xmastree", "TreasureChest_meadows", "piece_TrainingDummy",
    }
    check(not [x for x in obtainable if every.get(x, {}).get("unobtainable")],
          f"known-obtainable content isn't unobtainable ({[x for x in obtainable if every.get(x, {}).get('unobtainable')]})")
    check(not [x for x in obtainable if x not in every], f"known-obtainable ids exist ({[x for x in obtainable if x not in every]})")
    for kind, coll, share in (("items", items, 0.06), ("creatures", creatures, 0.2), ("pieces", pieces, 0.15)):
        n = sum(1 for e in coll.values() if e.get("unobtainable"))
        check(n <= share * len(coll), f"{kind}: {n} unobtainable, at most {share:.0%} of {len(coll)}")

    tagged = {"wood_roof_67": "Roofing", "sign": "Decor", "FeastMeadows": "Feasts", "piece_chest_wood": "Storage"}
    check(all(t in pieces[x].get("tags", []) for x, t in tagged.items()), "pieces: build menu tags (Piece.m_usage)")
    check(all(p.get("tags") for p in pieces.values() if p.get("tools") and not p.get("unobtainable")),
          "every buildable piece has a build menu tag")
    check(not pieces["sign_notext"].get("tags"), "world copies are in no build menu (sign_notext)")

    # Progression stages (#24): the metal ladder, a boss per biome, and rules that would break silently.
    locations = load("locations.json")
    check(len(locations) > 100 and all(x["biomes"] for x in locations), f"locations: {len(locations)} with biomes")
    stages = {
        "Wood": "Meadows", "FineWood": "BlackForest",  # bronze axe (Early Axes are STAGE_IGNORED_TOOLS)
        "Copper": "BlackForest", "Bronze": "BlackForest", "Iron": "Swamp", "Silver": "Mountain",
        "BlackMetal": "Plains", "Eitr": "Mistlands", "FlametalNew": "AshLands",
        "SwordBronze": "BlackForest", "SwordIron": "Swamp", "SwordBlackmetal": "Plains",
        "ArmorFlametalChest": "AshLands",  # black forge level 3: two extensions
        "forge": "BlackForest", "blastfurnace": "Mountain", "Karve": "BlackForest", "VikingShip": "Swamp",
        "Eikthyr": "Meadows", "gd_king": "BlackForest", "Bonemass": "Swamp", "Dragon": "Mountain",
        "GoblinKing": "Plains", "SeekerQueen": "Mistlands", "Fader": "AshLands", "FrozenKing": "DeepNorth",
        "Hatchling": "Mountain",  # the drake raid only comes after Bonemass
        "Goblin": "Plains",  # Hildir's fuling raid needs her third chest
        "JotunWarrior": "DeepNorth",  # its everywhere spawn needs the Fimbulvinter event
        "Serpent": "Meadows",  # the sea counts from the start
    }
    effects = {e["id"]: e for e in load("status_effects.json")}
    stages |= {"GP_Eikthyr": "Meadows", "GP_Moder": "Mountain", "GP_Fader": "AshLands",  # trophy at the boss stone
               "Staff_shield": "Mistlands", "Tared": "Plains",  # a weapon's hit, a creature's attack
               "Skeleton_Poison": "BlackForest"}  # its alt-biome patch is only in later biomes
    every = {**every, **effects}
    wrong = {x: every.get(x, {}).get("stage") for x, s in stages.items() if every.get(x, {}).get("stage") != s}
    check(not wrong, f"stages of known content {wrong or ''}")
    unstaged = [x for x, e in every.items() if x not in effects and "stage" not in e and not e.get("unobtainable")
                and not e.get("internal") and not e.get("enemyOnly")]
    check(len(unstaged) <= 20, f"{len(unstaged)} reachable entries without a stage (at most 20) {unstaged[:10]}")

    # Tech tree (#25): every staged entry has the way it is got (`via`), whose needs are staged no later and never
    # lead back to it.
    order = {s: n for n, s in enumerate(("Meadows", "BlackForest", "Swamp", "Mountain", "Plains", "Mistlands",
                                         "AshLands", "DeepNorth"))}
    node = {("item", k): v for k, v in items.items()} | {("creature", k): v for k, v in creatures.items()} \
        | {("piece", k): v for k, v in pieces.items()}
    needs = lambda e: [(k, n[k]) for n in e.get("via", {}).get("needs", []) for k in ("item", "creature", "piece") if k in n]
    check(all("via" in e for e in node.values() if e.get("stage")), "every staged entry has a via")
    later = [(k, n) for k, e in node.items() for n in needs(e)
             if n not in node or order.get(node[n].get("stage"), 99) > order.get(e.get("stage"), -1)]
    check(not later, f"via needs exist and are staged no later than what needs them {later[:5]}")
    state = {}  # 1 = on the current path, 2 = done

    def cyclic(k) -> bool:
        if state.get(k) == 1:
            return True
        if state.get(k) == 2:
            return False
        state[k] = 1
        bad = any(cyclic(n) for n in needs(node.get(k, {})))
        state[k] = 2
        return bad
    check(not any(cyclic(k) for k in node), "via graph is acyclic")

    def requires(k, target) -> bool:  # target: a node or a test on one
        seen, todo = set(), [k]
        while todo:
            x = todo.pop()
            if x == target or callable(target) and target(x):
                return True
            if x not in seen:
                seen.add(x)
                todo += needs(node.get(x, {}))
        return False
    check(all(requires(k, t) for k, t in [(("piece", "piece_stonecutter"), ("item", "Iron")),
                                          (("item", "SwordIron"), lambda x: node.get(x, {}).get("extends") == "forge"),
                                          (("piece", "smelter"), ("item", "SurtlingCore")),
                                          (("item", "SwordIron"), ("item", "IronScrap"))]),
          "via spot checks: Stonecutter needs Iron, Iron Sword a forge extension, Smelter Surtling Core")

    raids = load("raids.json")
    ev = {e["id"]: e for e in raids["events"]}
    check(raids.get("intervalMin", 0) > 0 and 0 < raids.get("chance", 0) <= 100, "raids: roll interval and chance set")
    check({"army_eikthyr", "army_theelder", "army_bonemass", "army_moder", "army_goblin", "foresttrolls"} <= set(ev),
          f"raids: known vanilla raids present ({len(ev)} raids)")
    raid_spawns = {s["event"] for s in spawns if s.get("source") == "raid"}
    check(set(ev) <= raid_spawns, f"raids: every raid spawns something {sorted(set(ev) - raid_spawns)}")
    check("defeated_eikthyr" in ev.get("army_eikthyr", {}).get("notRequiredGlobalKeys", []),
          "raids: Eikthyr's army stops once Eikthyr is defeated")
    dangling("raid player items", [i for e in ev.values() for k in ("knownItems", "notKnownItems")
                                   for i in (e.get("player") or {}).get(k, [])], set(items))
    base = {p for p in pieces if pieces[p].get("playerBase")}
    check({"piece_workbench", "bed", "fire_pit", "portal_wood"} <= base and len(base) < 100,
          f"pieces: base pieces for raids ({len(base)}) include workbench, bed, campfire, portal")
    check(all(c.get("faction") for c in creatures.values()), "creatures: every creature has a faction")
    forge = next((x for x in load("locations.json") if x["id"] == "AncientUpgradeStation"), {})
    check(forge.get("biomes") == ["Mountain"] and forge["placement"].get("unique")
          and forge["placement"].get("minDistance", 0) >= 500,
          "locations: Forge of Potential is unique, in the Mountain, at least 500 m from the centre")
    idols = [f"Upgrader{n}{k}" for n in range(8) for k in ("Weapon", "Armor")]
    check(all(items.get(i, {}).get("upgrader") and not items[i].get("unobtainable") for i in idols),
          "items: the 16 Battle/Protection Idols are reachable upgrader resources")

    print()
    if failures:
        print(f"VERIFY DATA FAILED: {len(failures)} check(s)")
        return 1
    print("VERIFY DATA PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

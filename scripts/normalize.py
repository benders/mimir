#!/usr/bin/env python3
"""Normalize a raw dump into the compact site data in data/. Stdlib only.

    scripts/normalize.py [raw_dir] [out_dir]    # default: .cache/dump/public/raw -> data/

The raw dump mirrors the game's own field layout (tens of MB). This keeps what a player looks
up, with English text resolved, ids = prefab names, and references as ids. Output is
deterministic (sorted, no timestamps) so a game update shows up as a readable git diff.

Conventions in the output:
  - Empty/zero/false/"Normal" values are omitted; a missing key means "none".
  - Damage maps use the game's damage type names without the m_ prefix (slash, fire, ...).
  - "icon" is a file name stem in the icons dir (<icon>.png).
"""
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / ".cache/dump/public/raw"
OUT = ROOT / "data"

TOKEN = re.compile(r"\$([A-Za-z0-9_]+)")
RICH_TEXT = re.compile(r"</?(?:color|b|i|size)\b[^>]*>", re.I)  # Unity rich-text tags
unresolved: set[str] = set()
skipped_refs: set[str] = set()  # references to prefabs that aren't items/creatures (projectiles, ambient fx)


def load(rel: str):
    return json.loads((RAW / rel).read_text(encoding="utf-8"))


TRANSLATIONS: dict[str, str] = {}
PREFABS: dict[str, dict] = {}
SUBPREFABS: dict[str, dict] = {}  # non-networked prefabs referenced by the above (summon abilities); lookup only


def setup(raw: Path, out: Path = OUT) -> None:
    """Point the module at a raw dump and load the shared tables (also used by the tests)."""
    global RAW, OUT
    RAW, OUT = Path(raw), Path(out)
    TRANSLATIONS.clear()
    TRANSLATIONS.update(load("localization/English.json"))
    PREFABS.clear()
    for f in sorted((RAW / "prefabs").glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        PREFABS[p["name"]] = p
    SUBPREFABS.clear()
    if (RAW / "subprefabs").is_dir():
        for f in sorted((RAW / "subprefabs").glob("*.json")):
            p = json.loads(f.read_text(encoding="utf-8"))
            SUBPREFABS[p["name"]] = p
    unresolved.clear()
    skipped_refs.clear()


def text(s: str | None) -> str | None:
    """Resolve $tokens to English, the way the game's Localization.Localize does, as plain text."""
    t = localize(s)
    return RICH_TEXT.sub("", t).strip() or None if t else None


def styled(s: str | None) -> bool:
    """Whether the English text carries rich-text styling (named minibosses: <color=orange>Brenna</color>)."""
    return bool(RICH_TEXT.search(localize(s) or ""))


def localize(s: str | None) -> str | None:
    if not s:
        return None

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in TRANSLATIONS:
            return TRANSLATIONS[key]
        unresolved.add(key)
        return m.group(0)

    return TOKEN.sub(sub, s).strip() or None


def ref(v) -> str | None:
    """Id of a referenced prefab or asset."""
    if isinstance(v, dict):
        return v.get("$ref") or v.get("$asset")
    return None


def icon(v) -> str | None:
    if isinstance(v, dict) and "$sprite" in v:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", v["$sprite"])  # same as extract-icons.py
    return None


def prune(v):
    """Drop empty values recursively, so absent == none/zero/false."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            x = prune(x)
            if x is None or x is False or x == "" or x == [] or x == {} or (type(x) in (int, float) and x == 0):
                continue
            out[k] = x
        return out
    if isinstance(v, list):
        return [prune(x) for x in v]
    return v


def strip_m(key: str) -> str:
    return key[2:] if key.startswith("m_") else key


def damages(d: dict | None) -> dict:
    return {strip_m(k): v for k, v in (d or {}).items() if v}


def modifiers(d: dict | None) -> dict:
    """HitData.DamageModifiers struct -> {type: modifier}, non-Normal only."""
    return {strip_m(k): v for k, v in (d or {}).items() if v != "Normal"}


def modifier_list(lst: list | None) -> dict:
    """[{m_type, m_modifier}] -> {type: modifier}."""
    return {m["m_type"].lower(): m["m_modifier"] for m in lst or [] if m["m_modifier"] != "Normal"}


def drop_table(t: dict | None) -> dict | None:
    if not t or not t.get("m_drops"):
        return None
    return {
        "min": t["m_dropMin"], "max": t["m_dropMax"], "chance": t["m_dropChance"], "oneOfEach": t["m_oneOfEach"],
        "items": [{"item": ref(d["m_item"]), "min": d["m_stackMin"], "max": d["m_stackMax"], "weight": d["m_weight"]}
                  for d in t["m_drops"] if keep(ref(d["m_item"]), is_item, is_creature)],
    }


def requirements(lst: list | None) -> list:
    return [{
        "item": ref(r["m_resItem"]), "amount": r["m_amount"], "perLevel": r["m_amountPerLevel"],
        "noRecover": not r["m_recover"], "upgrader": r.get("m_upgraderResource", False),
    } for r in lst or [] if ref(r["m_resItem"])]


# ---------------------------------------------------------------------------------------------
# Prefabs

def is_item(name: str | None) -> bool:
    return name in PREFABS and PREFABS[name]["isItem"]


def is_creature(name: str | None) -> bool:
    p = PREFABS.get(name)
    return p is not None and (has(p, "Humanoid") or has(p, "Character")) and not has(p, "Player")


def keep(name: str | None, *preds) -> bool:
    """Whether a reference points at something the site shows; records the ones it drops."""
    if name is None:
        return False
    if any(p(name) for p in preds):
        return True
    skipped_refs.add(name)
    return False


def has(p: dict, type_name: str) -> bool:
    """Whether the prefab's root object has the component (comp() is falsy for one without fields)."""
    return comp(p, type_name) is not None


def comp(p: dict, type_name: str) -> dict | None:
    """Fields of a component on the prefab's root object."""
    return next((c["fields"] for c in p["components"] if c["type"] == type_name and "path" not in c), None)


def attack(a: dict | None) -> dict | None:
    if not a or not a.get("m_attackAnimation"):
        return None
    return {
        "type": a["m_attackType"], "stamina": a["m_attackStamina"], "eitr": a["m_attackEitr"],
        "health": a["m_attackHealth"], "healthPercentage": a["m_attackHealthPercentage"],
        "damageMultiplier": a["m_damageMultiplier"] if a["m_damageMultiplier"] != 1 else 0,
        "projectile": ref(a.get("m_attackProjectile")),
        "projectiles": a["m_projectiles"] if a["m_projectiles"] > 1 else 0,
    }


def item(name: str, p: dict) -> dict | None:
    drop = comp(p, "ItemDrop")
    if not drop:
        return None
    s = drop["m_itemData"]["m_shared"]
    icons = [i for i in map(icon, s["m_icons"] or []) if i]
    food = None
    if s["m_food"] or s["m_foodStamina"] or s["m_foodEitr"]:
        food = {"health": s["m_food"], "stamina": s["m_foodStamina"], "eitr": s["m_foodEitr"],
                "duration": s["m_foodBurnTime"], "regen": s["m_foodRegen"], "drink": s["m_isDrink"]}
    durability = None
    if s["m_useDurability"]:
        durability = {"max": s["m_maxDurability"], "perLevel": s["m_durabilityPerLevel"],
                      "drain": s["m_useDurabilityDrain"], "repairable": s["m_canBeReparied"]}
    stat_mods = {strip_m(k)[: -len("Modifier")]: v for k, v in s.items()
                 if re.fullmatch(r"m_\w+Modifier", k) and type(v) in (int, float) and v}
    return {
        "id": name,
        "name": text(s["m_name"]),
        "description": text(s["m_description"]),
        "type": s["m_itemType"],
        "icon": icons[0] if icons else None,
        "variants": icons if len(icons) > 1 else None,
        "internal": not icons,  # attack/ability items creatures use, never in an inventory
        "weight": s["m_weight"],
        "value": s["m_value"],
        "stack": s["m_maxStackSize"],
        "maxQuality": s["m_maxQuality"],
        "noTeleport": not s["m_teleportable"],
        "dlc": s["m_dlc"],
        "skill": s["m_skillType"] if s["m_skillType"] != "None" else None,
        "toolTier": s["m_toolTier"],
        "damages": damages(s["m_damages"]),
        "damagesPerLevel": damages(s["m_damagesPerLevel"]),
        "attackForce": s["m_attackForce"],
        "backstab": s["m_backstabBonus"],
        "armor": s["m_armor"],
        "armorPerLevel": s["m_armorPerLevel"],
        "block": s["m_blockPower"],
        "blockPerLevel": s["m_blockPowerPerLevel"],
        "parryForce": s["m_deflectionForce"],
        "parryForcePerLevel": s["m_deflectionForcePerLevel"],
        "parryBonus": s["m_timedBlockBonus"],
        "durability": durability,
        "attack": attack(s.get("m_attack")),
        "secondaryAttack": attack(s.get("m_secondaryAttack")),
        "ammoType": s["m_ammoType"],
        "food": food,
        "modifiers": stat_mods,
        "damageModifiers": modifier_list(s["m_damageModifiers"]),
        "equipEffect": ref(s["m_equipStatusEffect"]),
        "consumeEffect": ref(s["m_consumeStatusEffect"]),
        "set": {"name": s["m_setName"], "size": s["m_setSize"], "effect": ref(s["m_setStatusEffect"])} if s["m_setName"] else None,
        "buildTable": ref(s["m_buildPieces"]),
    }


WEAPON_TYPES = {"OneHandedWeapon", "TwoHandedWeapon", "TwoHandedWeaponLeft", "Bow", "Torch", "Tool"}
AMMO_TYPES = {"Ammo", "AmmoNonEquipable"}
# Fields only some item types use; every ItemDrop carries the defaults (armor 10, block 10, skill Swords...).
ARMOR_FIELDS = {"armor", "armorPerLevel"}  # Player.GetBodyArmor sums helmet, chest, legs and shoulder only
BLOCK_FIELDS = {"block", "blockPerLevel", "parryForce", "parryForcePerLevel", "parryBonus"}  # Humanoid.GetCurrentBlocker:
# the left-hand item (shield, bow, torch), else the weapon
ATTACK_FIELDS = {"skill", "toolTier", "damages", "damagesPerLevel", "attackForce", "backstab", "attack", "secondaryAttack"}


def catapult_ammo() -> set[str]:
    """Items a Catapult fires with damage: its default ammo and m_includeItemsOverride (m_onlyIncludedItemsDealDamage)."""
    out = set()
    for p in PREFABS.values():
        if c := comp(p, "Catapult"):
            out |= {ref(c["m_defaultAmmo"])} | {ref(x) for x in c.get("m_includeItemsOverride") or []}
    return out - {None}


def prune_item_fields(items: list[dict]) -> None:
    """Drop the stat fields an item's type never uses (#7, #19). Internal attack items keep everything: creatures
    use them whatever their type."""
    ammo = catapult_ammo()
    for i in items:
        if i["internal"]:
            continue
        t, drop = i["type"], set()
        if t not in {"Helmet", "Chest", "Legs", "Shoulder"}:
            drop |= ARMOR_FIELDS
        if t not in WEAPON_TYPES | {"Shield"}:
            drop |= BLOCK_FIELDS
        if t not in WEAPON_TYPES | AMMO_TYPES and i["id"] not in ammo:
            drop |= ATTACK_FIELDS - ({"skill"} if t == "Shield" else set())  # shields train Blocking
        for k in drop:
            i.pop(k, None)


def item_type(name: str) -> str | None:
    drop = comp(PREFABS[name], "ItemDrop") if name in PREFABS else None
    return drop["m_itemData"]["m_shared"]["m_itemType"] if drop else None


def picked_items(src: dict) -> set[str]:
    """Items a pickable source gives: its `item`, or any of its `oneOf` choices."""
    pk = src.get("pickable") or {}
    return {x["item"] for x in pk.get("oneOf", [pk]) if "item" in x}


def mark_enemy_only(items: list, creatures: list, recipes: list, procs: list, sources: list, pieces: list) -> None:
    """Flag items players can't get and that only exist for enemies: no recipe, drop, source, conversion or piece
    yields them, and they are either carried by a creature (Dvergr crossbow, FW_* Fallen Warrior and SP_* Shadow
    gear) or a prefixed copy of an obtainable item with the same name (unused SP_* leftovers). Items that are merely
    unobtainable here (fishing and traders aren't modelled yet) stay visible. The site hides enemyOnly items."""
    carried = {i for c in creatures for i in c.get("attacks", []) + c.get("equipment", [])}
    obtainable = {r.get("item") for r in recipes} | {p["to"] for p in procs}
    obtainable |= {d["item"] for c in creatures for d in c.get("drops", [])}
    for src in sources:
        obtainable |= {d["item"] for d in (src.get("drops") or {}).get("items", [])}
        obtainable |= picked_items(src)
    obtainable |= {p["id"] for p in pieces}  # e.g. feast items placed as pieces
    by_id = {i["id"]: i for i in items}

    def is_copy(i: dict) -> bool:
        orig = by_id.get(i["id"].split("_", 1)[-1])
        return orig is not None and orig is not i and orig["id"] in obtainable and orig["name"] == i["name"]

    for i in items:
        if not i["internal"] and i["id"] not in obtainable and (i["id"] in carried or is_copy(i)):
            i["enemyOnly"] = True


def reachable(items: list, creatures: list, pieces: list, recipes: list, procs: list, sources: list,
              spawn_list: list) -> tuple[set, set, set]:
    """Ids of the items, creatures and pieces a player can get to, by fixed point from what the world offers:
    sources, spawns and enabled pieces in a build menu, then enabled recipes with reachable ingredients, drops of
    reachable creatures (a creature dropped by one, like a miniboss's second phase, is reached too), conversions
    of reachable inputs, eggs laid by a reachable creature, summons of a reachable summoner, boss phases of a reachable phase, creature-pieces (training dummy) whose cost is reachable. Pieces standing in a location (`locations`) count. Chests in locations and trader stock count (as
    sources; trader keys are ignored, Coins must be reachable), fish via their bait, honey and sap from buildable pieces whose cost is reachable (sap
    needs its root in the world). World sources count when placed (`biomes`, `locations`, `placedBy`, or a
    `becomes` stage of a placed one); a placed source whose `becomes` is an item yields it (Dvergr altar crystals). Incomplete while quests aren't modelled (#20)."""
    by_creature = {c["id"]: c for c in creatures}
    got_creatures = {s["creature"] for s in spawn_list if s["source"] not in ("summon", "phase")}
    traders = [src for src in sources if src["kind"] == "trader"]
    got_pieces = {p["id"] for p in pieces if (p.get("enabled") or p.get("season")) and p.get("tools")}
    got = set()
    fish = [src for src in sources if src["kind"] == "fishing"]
    made = [p for p in pieces if p["id"] in got_pieces and (pr := p.get("produces")) and pr["item"]
            and pr.get("connectsTo", {"biomes": True}).get("biomes")]
    by_piece = {p["id"]: p for p in pieces}
    item_ids = {i["id"] for i in items}
    world = [src for src in sources if src["kind"] not in ("fishing", "trader")]
    placed = {src["id"] for src in world if src["kind"] == "container" or src.get("biomes") or src.get("locations")}
    while True:
        before = len(got), len(got_creatures)
        for src in world:  # a source counts once placed: in the world, made by an affordable piece, or a stage of one
            if src["id"] in placed:
                if src.get("becomes") in item_ids:  # breaks into an item (Destructible.m_spawnWhenDestroyed)
                    got.add(src["becomes"])
                elif src.get("becomes"):
                    placed.add(src["becomes"])
            elif any(pc in got_pieces and all(r["item"] in got for r in by_piece[pc]["resources"])
                     for pc in src.get("placedBy", [])):
                placed.add(src["id"])
        for src in world:
            if src["id"] in placed:
                got |= {d["item"] for d in (src.get("drops") or {}).get("items", [])}
                got |= picked_items(src)
        got |= {r["item"] for r in recipes if r.get("item") and (r.get("enabled") or r.get("season"))
                and all(x["item"] in got for x in r["resources"] if not x.get("upgrader"))}
        dropped = {d["item"] for c in got_creatures for d in by_creature.get(c, {}).get("drops", [])}
        got |= dropped
        got_creatures |= dropped & by_creature.keys()
        for s in spawn_list:  # a summon needs its summoner (the creature carrying the item, else the item itself)
            if s["source"] in ("summon", "phase") and (s["parent"] in got_creatures if "parent" in s else s["item"] in got):
                got_creatures.add(s["creature"])
        got_creatures |= {c for c in got_pieces if all(r["item"] in got for r in by_piece[c]["resources"])} \
            & by_creature.keys()  # a buildable piece that is a creature (the training dummy)
        got |= {s["creature"] for s in spawn_list if s["source"] == "offspring" and s["parent"] in got_creatures
                and s["creature"] in item_ids}  # eggs laid by a creature we have
        if "Coins" in got:
            got |= {x["item"] for t in traders for x in t["sells"]}
        got |= {p["to"] for p in procs if p["from"] in got}
        got |= {p["id"] for p in pieces if p["id"] in got_pieces and p["id"] in item_ids  # feasts: item and piece in one
                and all(r["item"] in got for r in p["resources"])}
        for pc in made:  # a placed piece needs its cost; sap also its root, a world object
            if all(r["item"] in got for r in pc["resources"]):
                got.add(pc["produces"]["item"])
        for f in fish:
            if f["id"] in got_creatures and any(b["item"] in got for b in f["baits"]):
                got.add(f["id"])
                got |= {d["item"] for d in (f.get("drops") or {}).get("items", [])}
        if (len(got), len(got_creatures)) == before:
            return got, got_creatures, got_pieces | {p["id"] for p in pieces if p.get("locations")}


def seasons(pieces: list, recipes: list) -> None:
    """Tag the pieces and recipes of each SeasonalItemGroup with `season`: name and (day, month) start and end, both
    inclusive (SeasonalItemGroup.IsInSeason; an end before the start wraps over New Year). The game lets a disabled
    piece or recipe through while the season is current (PieceTable, Player.UpdateCurrentSeason)."""
    by_piece = {p["id"]: p for p in pieces}
    by_recipe = {r["id"]: r for r in recipes}
    for g in load("world/seasons.json"):
        f = g["fields"]
        s = {"name": g["name"], "start": f["_startDate"], "end": f["_endDate"]}
        for pc in f["Pieces"]:
            if ref(pc) in by_piece:
                by_piece[ref(pc)]["season"] = s
        for r in f["Recipes"]:
            if ref(r) in by_recipe:
                by_recipe[ref(r)]["season"] = s


def mark_unobtainable(items: list, creatures: list, pieces: list, recipes: list, procs: list, sources: list,
                      spawn_list: list) -> None:
    """Flag every item, creature and piece reachable() can't get to: unreleased, test, cheat and legacy content
    (Hive, SwordCheat, HealthUpgrade_*, OLD_wood_roof, unplaced *_sleeping variants). Internal and enemyOnly items
    are hidden already. The site hides unobtainable entries; verify_data guards against a source gap hiding real
    content (#35)."""
    got = reachable(items, creatures, pieces, recipes, procs, sources, spawn_list)
    for entries, ids in zip((items, creatures, pieces), got):
        for e in entries:
            if e["id"] not in ids and not e.get("internal") and not e.get("enemyOnly"):
                e["unobtainable"] = True


def carried_items(c: dict) -> set[str]:
    """Item ids a Humanoid/Character carries: default, random weapon/shield/armor, random sets and items."""
    carried = set()
    for v in (c.get("m_defaultItems") or []) + (c.get("m_randomWeapon") or []) + (c.get("m_randomShield") or []) \
            + (c.get("m_randomArmor") or []):
        carried.add(ref(v))
    for s in c.get("m_randomSets") or []:
        carried.update(ref(v) for v in s["m_items"])
    carried.update(ref(r["m_prefab"]) for r in c.get("m_randomItems") or [])
    return {a for a in carried if keep(a, is_item)}


def creature(name: str, p: dict) -> dict | None:
    c = comp(p, "Humanoid") or comp(p, "Character")
    if c is None or has(p, "Player"):
        return None
    carried = carried_items(c)
    # weapons (incl. the internal attack items) are attacks; armor, shields and trinkets are equipment
    attacks = {a for a in carried if item_type(a) in WEAPON_TYPES}
    drops = [{
        "item": ref(d["m_prefab"]), "min": d["m_amountMin"], "max": d["m_amountMax"], "chance": d["m_chance"],
        "onePerPlayer": d["m_onePerPlayer"], "levelMultiplier": d["m_levelMultiplier"],
    } for d in (comp(p, "CharacterDrop") or {}).get("m_drops", []) if keep(ref(d["m_prefab"]), is_item, is_creature)]
    tame = comp(p, "Tameable")
    ai = comp(p, "MonsterAI") or comp(p, "AnimalAI") or {}
    return {
        "id": name,
        "name": text(c["m_name"]),
        "named": styled(c["m_name"]),
        "faction": c["m_faction"],
        "group": c["m_group"],
        "boss": c["m_boss"],
        "defeatKey": c.get("m_defeatSetGlobalKey"),
        "health": c["m_health"],
        "damageModifiers": modifiers(c["m_damageModifiers"]),
        "speed": {"walk": c["m_walkSpeed"], "run": c["m_runSpeed"], "swim": c["m_swimSpeed"] if c["m_canSwim"] else 0,
                  "fly": c["m_flyFastSpeed"] if c["m_flying"] else 0},
        "attacks": sorted(attacks),
        "equipment": sorted(carried - attacks),
        "drops": drops,
        "tameable": {
            "fedDuration": tame["m_fedDuration"], "tamingTime": tame["m_tamingTime"],
            "commandable": tame["m_commandable"], "food": sorted(filter(None, map(ref, ai.get("m_consumeItems") or []))),
        } if tame else None,
        "afraidOfFire": ai.get("m_afraidOfFire"),
        "avoidWater": ai.get("m_avoidWater"),
    }


def piece(name: str, p: dict, tools: dict[str, list[str]]) -> dict | None:
    pc = comp(p, "Piece")
    if not pc:
        return None
    wnt = comp(p, "WearNTear") or {}
    station = comp(p, "CraftingStation")
    ext = comp(p, "StationExtension")
    return {
        "id": name,
        "name": text(pc["m_name"]),
        "description": text(pc["m_description"]),
        "icon": icon(pc["m_icon"]),
        "enabled": pc["m_enabled"],
        "category": pc["m_category"],
        "tools": sorted(tools.get(name, [])),
        "station": ref(pc["m_craftingStation"]),
        "resources": requirements(pc["m_resources"]),
        "comfort": {"value": pc["m_comfort"], "group": pc["m_comfortGroup"] if pc["m_comfortGroup"] != "None" else None}
        if pc["m_comfort"] else None,
        "onlyInBiome": pc["m_onlyInBiome"] if pc["m_onlyInBiome"] != "None" else None,
        "health": wnt.get("m_health"),
        "material": wnt.get("m_materialType"),
        "damageModifiers": modifiers(wnt.get("m_damages")),
        "craftingStation": {"name": text(station["m_name"]), "buildRange": station["m_rangeBuild"],
                            "requiresRoof": station["m_craftRequireRoof"], "requiresFire": station["m_craftRequireFire"]}
        if station else None,
        "extends": ref(ext["m_craftingStation"]) if ext else None,
        "produces": produces(p),
        "dlc": pc["m_dlc"],
    }


def produces(p: dict) -> dict | None:
    """What a placed piece makes by itself: a Beehive's honey (`secPerUnit` each, up to `max`, only when its
    `biomes` allow) or a SapCollector's sap, which needs a world object (`connectsTo`: id and the biomes it grows in,
    from ZoneSystem vegetation) below it."""
    if b := comp(p, "Beehive"):
        return {"item": ref(b["m_honeyItem"]), "secPerUnit": b["m_secPerUnit"], "max": b["m_maxHoney"],
                "biomes": biomes(b["m_biome"])}
    if s := comp(p, "SapCollector"):
        root = ref(s["m_mustConnectTo"])
        where = []
        for v in load("world/ZoneSystem.json")[0]["fields"]["m_vegetation"]:
            if v["m_enable"] and ref(v["m_prefab"]) == root:
                where += [x for x in biomes(v["m_biome"]) if x not in where]
        return {"item": ref(s["m_spawnItem"]), "secPerUnit": s["m_secPerUnit"], "max": s["m_maxLevel"],
                "connectsTo": {"id": root, "biomes": where}}
    return None


def processing(name: str, p: dict) -> list[dict]:
    """Smelter / CookingStation / Fermenter conversions, one entry per (station, from, to)."""
    out = []
    if s := comp(p, "Smelter"):
        for c in s["m_conversion"]:
            out.append({"station": name, "kind": "smelter", "from": ref(c["m_from"]), "to": ref(c["m_to"]), "amount": 1,
                        "time": s["m_secPerProduct"], "fuel": ref(s["m_fuelItem"]),
                        "fuelPerProduct": s["m_fuelPerProduct"] if s["m_fuelItem"] else 0, "capacity": s["m_maxOre"]})
    if s := comp(p, "CookingStation"):
        for c in s["m_conversion"]:
            out.append({"station": name, "kind": "cooking", "from": ref(c["m_from"]), "to": ref(c["m_to"]), "amount": 1,
                        "time": c["m_cookTime"], "fuel": ref(s.get("m_fuelItem")), "requiresFire": s["m_requireFire"]})
    if s := comp(p, "Fermenter"):
        for c in s["m_conversion"]:
            out.append({"station": name, "kind": "fermenter", "from": ref(c["m_from"]), "to": ref(c["m_to"]),
                        "amount": c["m_producedItems"], "time": s["m_fermentationDuration"]})
    # some stations list a conversion twice (blastfurnace FlametalOreNew, piece_FrostFoundry StaffSpiritCallerUncooked)
    return [x for x in {json.dumps(x, sort_keys=True): x for x in out}.values() if x["from"] and x["to"]]


def source(name: str, p: dict) -> dict | None:
    """World objects that yield items: pickables, ore veins, rocks, trees, logs, breakables."""
    entry: dict = {"id": name}
    if pk := comp(p, "Pickable"):
        entry.update(kind="pickable", name=text(pk["m_overrideName"]), pickable={
            "item": ref(pk["m_itemPrefab"]), "amount": pk["m_amount"], "respawnMinutes": pk["m_respawnTimeMinutes"]},
            drops=drop_table(pk["m_extraDrops"]))
    elif pi := comp(p, "PickableItem"):  # treasure piles: one of m_randomItemPrefabs, else m_itemPrefab x m_stack
        if opts := pi["m_randomItemPrefabs"]:  # PickableItem.SetupRandomPrefab: Random.Range(stackMin, stackMax + 1)
            entry.update(kind="pickable", pickable={"oneOf": [prune({"item": ref(r["m_itemPrefab"]),
                         "min": r["m_stackMin"], "max": r["m_stackMax"]}) for r in opts]})
        else:
            entry.update(kind="pickable", pickable={"item": ref(pi["m_itemPrefab"]), "amount": pi["m_stack"]})
    elif mr := comp(p, "MineRock") or comp(p, "MineRock5"):
        entry.update(kind="rock", name=text(mr["m_name"]), health=mr["m_health"], minToolTier=mr["m_minToolTier"],
                     damageModifiers=modifiers(mr.get("m_damageModifiers")), drops=drop_table(mr["m_dropItems"]))
    elif t := comp(p, "TreeBase"):
        entry.update(kind="tree", health=t["m_health"], minToolTier=t["m_minToolTier"],
                     damageModifiers=modifiers(t["m_damageModifiers"]), drops=drop_table(t["m_dropWhenDestroyed"]),
                     becomes=ref(t["m_logPrefab"]))
    elif t := comp(p, "TreeLog"):
        entry.update(kind="log", health=t["m_health"], minToolTier=t["m_minToolTier"],
                     damageModifiers=modifiers(t.get("m_damages")), drops=drop_table(t["m_dropWhenDestroyed"]),
                     becomes=ref(t.get("m_subLogPrefab")))
    elif d := comp(p, "Destructible"):
        dod = comp(p, "DropOnDestroyed") or {}
        entry.update(kind="destructible", health=d["m_health"], minToolTier=d["m_minToolTier"],
                     damageModifiers=modifiers(d["m_damages"]), drops=drop_table(dod.get("m_dropWhenDestroyed")),
                     becomes=ref(d.get("m_spawnWhenDestroyed")))
    elif (dod := comp(p, "DropOnDestroyed")) and (w := comp(p, "WearNTear")):  # wild beehives, props in locations
        entry.update(kind="destructible", health=w["m_health"], damageModifiers=modifiers(w["m_damages"]),
                     drops=drop_table(dod["m_dropWhenDestroyed"]))
    else:
        return None
    if not entry.get("drops") and not entry.get("pickable") and not entry.get("becomes"):
        return None
    if hover := comp(p, "HoverText"):
        entry["name"] = entry.get("name") or text(hover.get("m_text"))
    return entry


# ---------------------------------------------------------------------------------------------
# ScriptableObjects and world


def recipe(r: dict) -> dict:
    f = r["fields"]
    return {
        "id": r["name"],
        "item": ref(f["m_item"]),
        "amount": f["m_amount"],
        "enabled": f["m_enabled"],
        "station": ref(f["m_craftingStation"]),
        "stationLevel": f["m_minStationLevel"],
        "repairStation": ref(f["m_repairStation"]),
        "upgradeOnly": f["m_noCraftOnlyUpgrade"],
        "anyOneIngredient": f["m_requireOnlyOneIngredient"],
        "resources": requirements(f["m_resources"]),
    }


SE_PRESENTATION = re.compile(r"Message|Effect|Icon|Animation|^m_(name|tooltip|icon|category|ttl|cooldown|character|hitVariant)$")


def status_effect(e: dict, defaults: dict[str, dict]) -> dict:
    """Name, text and timing, plus every gameplay field that differs from the type's default."""
    f, base = e["fields"], defaults.get(e["type"], {})
    stats = {}
    for k, v in f.items():
        if SE_PRESENTATION.search(k) or v == base.get(k, object()):
            continue
        if k == "m_mods":
            v = modifier_list(v)
        elif k == "m_percentigeDamageModifiers":
            v = damages(v)
        elif isinstance(v, dict) and ("$ref" in v or "$asset" in v):
            v = ref(v)
        stats[strip_m(k)] = v
    return {
        "id": e["name"],
        "type": e["type"],
        "name": text(f.get("m_name")),
        "tooltip": text(f.get("m_tooltip")),
        "icon": icon(f.get("m_icon")),
        "category": f.get("m_category"),
        "duration": f.get("m_ttl"),
        "cooldown": f.get("m_cooldown"),
        "stats": stats,
    }


BIOME_BITS = {"Meadows": 1, "Swamp": 2, "Mountain": 4, "BlackForest": 8, "Plains": 0x10, "AshLands": 0x20,
              "DeepNorth": 0x40, "Ocean": 0x100, "Mistlands": 0x200}  # Heightmap.Biome


def biomes(v: str) -> list[str]:
    """Heightmap.Biome flags as names. Flag enums serialize as "A, B", "All", or a bare number (-1 = all bits)."""
    bits = v.strip()
    if bits == "All":
        bits = sum(BIOME_BITS.values())
    elif bits.lstrip("-").isdigit():
        bits = int(bits)
    else:
        return [b for b in bits.split(", ") if b in BIOME_BITS]
    return [b for b, bit in BIOME_BITS.items() if bits & bit]


def levels(lo: int, hi: int) -> list[int]:
    return sorted([lo, hi])  # some spawners have min/max swapped


def offered_creatures(boss: str | None) -> list[str]:
    """What an offering bowl summons: the boss creature, or a non-networked group prefab (the memorial's three
    warriors) whose child objects are named after creature prefabs ("FallenWarrior (1)")."""
    if keep(boss, is_creature):
        return [boss]
    kids = {re.sub(r" \(\d+\)$", "", c["path"].rsplit("/", 1)[-1]) for c in SUBPREFABS.get(boss, {"components": []})["components"]
            if "path" in c and c["type"] == "Humanoid"}
    return sorted(k for k in kids if is_creature(k))


def spawners_in(p: dict) -> list[dict]:
    """Creatures placed by spawners inside a location or dungeon room."""
    out = []
    for c in p["components"]:
        t, f = c["type"], c["fields"]
        if t == "CreatureSpawner" and keep(ref(f["m_creaturePrefab"]), is_creature, is_item):
            out.append({"creature": ref(f["m_creaturePrefab"]), "levels": levels(f["m_minLevel"], f["m_maxLevel"]),
                        "respawnMinutes": f["m_respawnTimeMinuts"]})
        elif t == "SpawnArea":
            out += [{"creature": ref(x["m_prefab"]), "levels": levels(x["m_minLevel"], x["m_maxLevel"]), "respawning": True}
                    for x in f["m_prefabs"] if keep(ref(x["m_prefab"]), is_creature, is_item)]
        elif t == "OfferingBowl":
            for boss in offered_creatures(ref(f["m_bossPrefab"])):
                out.append({"creature": boss, "summon": prune({"item": ref(f["m_bossItem"]), "amount": f["m_bossItems"]})})
    return out


def merge_spawners(found: list[dict]) -> list[dict]:
    """One entry per creature: widest level range; respawning if any spawner respawns."""
    by = {}
    for x in found:
        e = by.setdefault(x["creature"], {"creature": x["creature"]})
        if "levels" in x:
            lo, hi = e.get("levels", x["levels"])
            e["levels"] = [min(lo, x["levels"][0]), max(hi, x["levels"][1])]
        if x.get("respawning") or x.get("respawnMinutes"):
            e["respawning"] = True
        if "summon" in x:
            e["summon"] = x["summon"]
    return [by[k] for k in sorted(by)]


def load_dir(rel: str) -> dict[str, dict]:
    d = RAW / rel
    return {p["name"]: p for p in (json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json")))} \
        if d.is_dir() else {}


def world_spawn(s: dict, lst: str, alt: str = "") -> dict | None:
    prefab = ref(s["m_prefab"])
    # some entries place a CreatureSpawner prefab rather than the creature itself
    if prefab in PREFABS and (cs := comp(PREFABS[prefab], "CreatureSpawner")):
        prefab = ref(cs["m_creaturePrefab"])
    if not s["m_enabled"] or s.get("m_devDisabled") or not keep(prefab, is_creature, is_item):
        return None
    return {
        "creature": prefab,
        "source": "world",
        "list": lst,
        **({"altBiome": alt} if alt else {}),
        "biomes": biomes(s["m_biome"]),
        "biomeArea": s["m_biomeArea"],
        "maxSpawned": s["m_maxSpawned"],
        "interval": s["m_spawnInterval"],
        "chance": s["m_spawnChance"],
        "groupSize": [s["m_groupSizeMin"], s["m_groupSizeMax"]],
        "levels": [s["m_minLevel"], s["m_maxLevel"]],
        "day": s["m_spawnAtDay"],
        "night": s["m_spawnAtNight"],
        "altitude": [s["m_minAltitude"], s["m_maxAltitude"]],
        "requiredGlobalKey": s["m_requiredGlobalKey"],
        "requiredEnvironments": s["m_requiredEnvironments"],
        "huntPlayer": s["m_huntPlayer"],
    }


def world_spawns() -> list[dict]:
    """SpawnSystem: the ambient spawns of each biome, and those of the alt biomes (ZoneSystem's AltBiomeList:
    random patches within a biome that add spawns, `altBiome` is the patch's name; enabled ones only, like the game)."""
    out = []
    for lst in sorted(load("world/SpawnSystemList.json"), key=lambda s: s["name"]):
        out += filter(None, (world_spawn(s, lst["name"]) for s in lst["fields"]["m_spawners"]))
    for ref_ in load("world/ZoneSystem.json")[0]["fields"].get("m_altBiomeLists", []):
        for p in SUBPREFABS.get(ref_["$ref"], {"components": []})["components"]:
            for alt in p["fields"].get("m_alts", []) if p["type"] == "AltBiomeList" else []:
                if alt["m_enabled"]:
                    out += filter(None, (world_spawn(s, ref_["$ref"], alt["m_name"]) for s in alt["m_spawn"]))
    return out


def raid_spawns() -> list[dict]:
    """RandEventSystem: raids on player bases. The event's biome applies; its spawners use All."""
    out = []
    for e in sorted(load("world/RandEventSystem.json")[0]["fields"]["m_events"], key=lambda e: e["m_name"]):
        if not e["m_enabled"] or e.get("m_devDisabled"):
            continue
        for s in e["m_spawn"]:
            if not s["m_enabled"] or s.get("m_devDisabled") or not keep(ref(s["m_prefab"]), is_creature, is_item):
                continue
            out.append({
                "creature": ref(s["m_prefab"]),
                "source": "raid",
                "event": e["m_name"],
                "message": text(e["m_startMessage"]),
                "biomes": biomes(e["m_biome"]),
                "maxSpawned": s["m_maxSpawned"],
                "interval": s["m_spawnInterval"],
                "chance": s["m_spawnChance"],
                "groupSize": [s["m_groupSizeMin"], s["m_groupSizeMax"]],
                "levels": levels(s["m_minLevel"], s["m_maxLevel"]),
                "requiredGlobalKeys": e["m_requiredGlobalKeys"],
                "notRequiredGlobalKeys": e["m_notRequiredGlobalKeys"],
            })
    return out


def placed_in_locations():
    """(location, biomes, prefab, dungeon) for each enabled world location's own prefab and, as dungeon, every
    enabled room its DungeonGenerator can use (Room.Theme overlapping the generator's m_themes)."""
    locations, rooms = load_dir("locations"), load_dir("rooms")
    themes = load("room_themes.json") if (RAW / "room_themes.json").exists() else {}

    def theme_bits(v) -> int:
        return v if isinstance(v, int) else int(v) if v.isdigit() else sum(themes.get(t, 0) for t in v.split(", "))

    where = defaultdict(list)  # location prefab -> biomes, in ZoneSystem order
    for z in load("world/ZoneSystem.json")[0]["fields"]["m_locations"]:
        if z["m_enable"]:
            where[z["m_prefabName"]] += [b for b in biomes(z["m_biome"]) if b not in where[z["m_prefabName"]]]

    for name in sorted(where):
        if name not in locations:
            continue
        loc = locations[name]
        yield name, where[name], loc, False
        for g in (c["fields"] for c in loc["components"] if c["type"] == "DungeonGenerator"):
            bits = theme_bits(g["m_themes"])
            for r in rooms.values():
                if r.get("enabled") and theme_bits(r["theme"]) & bits:
                    yield name, where[name], r, True


def placed_prefabs(p: dict) -> set[str]:
    """Prefabs placed in a location or room: its hierarchy's network prefab `instances`. An `inactive` one (it or an
    ancestor is disabled in the asset) is skipped: ZoneSystem.SpawnLocation re-enables only objects enabled in the
    asset, so it is never created, except under a RandomSpawn ancestor (`randomSpawn.path`), which activates its own
    object when it has no ZNetView (RandomSpawn.SetSpawned; assumed to be the disabled one). A RandomSpawn `chance`
    under 100 still counts as placed: it is rolled per location."""
    return {i["prefab"] for i in p.get("instances", []) if not i.get("inactive") or "path" in i.get("randomSpawn", {})}


def with_instances(p: dict) -> list[dict]:
    """Components of a location or room plus those of the prefabs it places (the dump doesn't repeat
    them in the location: a Spawner_* object's CreatureSpawner, a chest's Container)."""
    return p["components"] + [c for n in sorted(placed_prefabs(p)) if n in PREFABS for c in PREFABS[n]["components"]]


def location_spawns() -> list[dict]:
    """Creature spawners, spawn areas and boss altars inside world locations and the dungeons they generate,
    including those of placed `Spawner_*` objects, and creatures placed directly."""
    found, biomes_of = defaultdict(list), {}
    for name, bs, p, dungeon in placed_in_locations():
        found[name, dungeon] += spawners_in({"components": with_instances(p)})
        found[name, dungeon] += [{"creature": n} for n in sorted(placed_prefabs(p)) if n in PREFABS and is_creature(n)]
        biomes_of[name] = bs
    out = []
    for name in sorted(biomes_of):
        for dungeon in (False, True):
            for e in merge_spawners(found[name, dungeon]):
                out.append({"creature": e.pop("creature"), "source": "dungeon" if dungeon else "location",
                            "location": name, "biomes": biomes_of[name], **e})
    return out


def location_containers() -> list[dict]:
    """Loot chests (Container default items) in locations and their dungeon rooms: one source of kind `container`
    per distinct name + drop table, with the locations it is found in (`dungeon`: in a room the location's
    dungeon generates)."""
    by = {}
    for name, bs, p, dungeon in placed_in_locations():
        for c in (c["fields"] for c in with_instances(p) if c["type"] == "Container"):
            if not (table := drop_table(c["m_defaultItems"])):
                continue
            title = text(c["m_name"])
            digest = hashlib.sha1(json.dumps(table, sort_keys=True).encode()).hexdigest()[:6]
            slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
            e = by.setdefault((title, digest), {"id": f"container_{slug}_{digest}", "kind": "container",
                                                "name": title, "drops": table, "locations": {}})
            e["locations"][name, dungeon] = {"location": name, "dungeon": dungeon}
    return sorted((dict(e, locations=[e["locations"][k] for k in sorted(e["locations"])]) for e in by.values()),
                  key=lambda e: e["id"])


def scene_instances() -> dict[str, set]:
    """prefab name -> {(location, dungeon)}: the location prefab itself, or a placed instance of the prefab in the
    location or in a room its dungeon generates."""
    found = defaultdict(set)
    for name, bs, p, dungeon in placed_in_locations():
        for inst in placed_prefabs(p) | {p["name"]}:
            found[inst].add((name, dungeon))
    return found


def place_pieces(pieces: list[dict]) -> None:
    """Record `locations` [{location, dungeon}] on pieces that can't be built (no build menu) but stand in a world
    location or one of its dungeon rooms: loot chests, ruined walls, props."""
    found = scene_instances()
    for pc in pieces:
        if not pc["tools"] and found.get(pc["id"]):
            pc["locations"] = [{"location": loc, "dungeon": d} for loc, d in sorted(found[pc["id"]])]


def place_sources(sources: list[dict]) -> None:
    """Record where each world source is placed: `biomes` (enabled ZoneSystem vegetation), `locations`
    [{location, dungeon}] (the location is the object, or an instance of it sits in the location or in a room its
    dungeon generates), `placedBy` (pieces that create it: Plant, Procreation, WispSpawner).
    Sources with none of these are not found anywhere in the world."""
    by = {s["id"]: s for s in sources if s["kind"] not in ("fishing", "trader", "container")}
    veg = defaultdict(list)
    for v in load("world/ZoneSystem.json")[0]["fields"]["m_vegetation"]:
        if v["m_enable"] and (pid := ref(v["m_prefab"])) in by:
            veg[pid] += [b for b in biomes(v["m_biome"]) if b not in veg[pid]]
    found = defaultdict(set)
    for inst, places in scene_instances().items():
        if inst in by:
            found[inst] |= places
    for name, bs, p, dungeon in placed_in_locations():
        for c in with_instances(p):  # objects a spawner makes (the Charred ballista)
            if c["type"] == "CreatureSpawner" and (spawned := ref(c["fields"]["m_creaturePrefab"])) in by:
                found[spawned].add((name, dungeon))
    made = defaultdict(set)
    for name, p in PREFABS.items():
        if not has(p, "Piece"):
            continue
        for c, field in (("Plant", "m_grownPrefabs"), ("Procreation", "m_offspring"), ("WispSpawner", "m_wispPrefab")):
            if cc := comp(p, c):
                v = cc[field]
                made[name] |= {r for x in (v if isinstance(v, list) else [v]) if (r := ref(x)) in by}
    for sid, e in by.items():
        if veg[sid]:
            e["biomes"] = veg[sid]
        if found[sid]:
            e["locations"] = [{"location": loc, "dungeon": d} for loc, d in sorted(found[sid])]
        if pieces := sorted(n for n, ids in made.items() if sid in ids):
            e["placedBy"] = pieces


def fishing(spawn_list: list[dict]) -> list[dict]:
    """Fish prefabs (Fish component) as sources of kind `fishing`: the baits they take (`baits` [{item, chance}]),
    the biomes they swim in (from their spawns) and the extra drops a catch can carry. The caught fish is the
    item with the same id."""
    out = []
    for name, p in PREFABS.items():
        if not (f := comp(p, "Fish")) or not p["isItem"]:
            continue
        biomes_of = []
        for s in spawn_list:
            if s["creature"] == name and s.get("biomes"):  # world, or cave pools in dungeons
                biomes_of += [b for b in s["biomes"] if b not in biomes_of]
        out.append({"id": name, "kind": "fishing", "name": text(f["m_name"]), "biomes": biomes_of,
                    "baits": [{"item": ref(b["m_bait"]), "chance": b["m_chance"]} for b in f["m_baits"]
                              if keep(ref(b["m_bait"]), is_item)],
                    "drops": drop_table(f["m_extraDrops"])})
    return out


def traders() -> list[dict]:
    """Traders (Trader component) standing in a world location, as sources of kind `trader`: what they `sell`
    (item, stack, price in coins, `requiredKey` global key that unlocks the offer) and the `locations` (with biomes)
    they are found in. The id is the trader's name in the location prefab (Haldor, Hildir, BogWitch)."""
    by = {}
    for name, bs, p, dungeon in placed_in_locations():
        for c in p["components"]:
            if c["type"] != "Trader":
                continue
            f = c["fields"]
            e = by.setdefault((c.get("path") or name).rsplit("/", 1)[-1], {"kind": "trader", "name": text(f["m_name"]),
                              "sells": [{"item": ref(i["m_prefab"]), "stack": i["m_stack"], "price": i["m_price"],
                                         "requiredKey": i["m_requiredGlobalKey"]} for i in f["m_items"]
                                        if keep(ref(i["m_prefab"]), is_item)], "locations": []})
            e["locations"].append({"location": name, "biomes": bs})
    return [{"id": k, **v} for k, v in sorted(by.items())]


def offspring_spawns() -> list[dict]:
    """Creatures born from another creature (Procreation; the offspring can be an egg item), hatched from an egg
    item (EggGrow) or grown up from another creature (Growup)."""
    out = []
    for name, p in PREFABS.items():
        if (c := comp(p, "Procreation")) and is_creature(name) and keep(ref(c["m_offspring"]), is_creature, is_item):
            out.append({"creature": ref(c["m_offspring"]), "source": "offspring", "parent": name})
        if (c := comp(p, "EggGrow")) and keep(ref(c["m_grownPrefab"]), is_creature):
            out.append({"creature": ref(c["m_grownPrefab"]), "source": "egg", "item": name})
        if (c := comp(p, "Growup")) and is_creature(name) and keep(ref(c["m_grownPrefab"]), is_creature):
            out.append({"creature": ref(c["m_grownPrefab"]), "source": "growup", "parent": name})
    return out


def summoned_creatures(target: str, seen: frozenset = frozenset()) -> list[str]:
    """Creatures made by an attack's prefab: a SpawnAbility's `m_spawnPrefab`, or a projectile's `m_spawnOnHit` /
    `m_randomSpawnOnHit` (followed, they are abilities or projectiles in turn), or a creature itself. Abilities
    are mostly non-networked, so they come from SUBPREFABS."""
    if not target or target in seen:
        return []
    p = PREFABS.get(target) or SUBPREFABS.get(target)
    if p and (ability := comp(p, "SpawnAbility")):
        return [r for x in ability["m_spawnPrefab"] if is_creature(r := ref(x))]
    if p and (pr := comp(p, "Projectile")):
        return [c for t in [ref(pr.get("m_spawnOnHit"))] + [ref(x) for x in pr.get("m_randomSpawnOnHit") or []]
                for c in summoned_creatures(t, seen | {target})]
    return [target] if is_creature(target) else []


def summoned_by(item_name: str) -> list[str]:
    """Creatures an attack item makes (staff summons, boss abilities): see `summoned_creatures`; the attack's
    `m_attackProjectile` is a projectile or, for boss abilities and some staffs, the SpawnAbility directly."""
    if not (drop := comp(PREFABS[item_name], "ItemDrop")):
        return []
    shared = drop["m_itemData"]["m_shared"]
    return sorted({c for a in (shared["m_attack"], shared["m_secondaryAttack"])
                   for c in summoned_creatures(ref(a.get("m_attackProjectile")))})


def spawned_hits(target: str, inherited: dict | None, seen: frozenset = frozenset()) -> list[dict]:
    """Damage dealt by an attack's spawned object and what it spawns in turn. `inherited` is the attack's damage when
    the game passes its HitData on (Attack.FireProjectileBurst -> Projectile.Setup / Aoe.Setup), else None and the
    object deals its own m_damage (SpawnAbility, Attack.m_spawnOnTrigger, ItemData m_spawnOnHit)."""
    if not target or target in seen:
        return []
    p, seen = PREFABS.get(target) or SUBPREFABS.get(target), seen | {target}
    if not p:
        return []
    if pr := comp(p, "Projectile"):
        spawn = ref(pr.get("m_spawnOnHit"))
        own = inherited if inherited is not None else damages(pr.get("m_damage"))
        out = [] if spawn and pr.get("m_onlySpawnedProjectilesDealDamage") else [{"kind": "projectile", "damages": own}]
        out += spawned_hits(spawn, inherited if pr.get("m_projectilesInheritHitData") else None, seen)
        return out + [h for r in pr.get("m_randomSpawnOnHit") or [] for h in spawned_hits(ref(r), None, seen)]
    if a := comp(p, "Aoe"):  # Aoe.Setup takes the attack's damage only with m_useAttackSettings
        return [{"kind": "area", "damages": inherited if inherited is not None and a.get("m_useAttackSettings", True)
                 else damages(a["m_damage"])}]
    if sa := comp(p, "SpawnAbility"):  # SpawnAbility.SetupProjectile / spawned Aoe: no HitData
        return [h for x in sa["m_spawnPrefab"] for h in spawned_hits(ref(x), None, seen)]
    return []


def attack_hits(name: str) -> list[dict] | None:
    """What a creature's attack item hits with when the damage goes through spawned objects (#9), None when the
    item's own damage is all there is. Only the primary attack: MonsterAI uses m_attack."""
    s = comp(PREFABS[name], "ItemDrop")["m_itemData"]["m_shared"]
    a, own = s["m_attack"], damages(s["m_damages"])
    hits, spawned = [], False
    if a["m_attackType"] == "Projectile":
        hits, spawned = spawned_hits(ref(a.get("m_attackProjectile")), own), True
    else:
        hits = [{"kind": "hit", "damages": own}]
    for extra in (ref(a.get("m_spawnOnTrigger")), ref(s.get("m_spawnOnHit")), ref(s.get("m_spawnOnHitTerrain"))):
        if extra:
            hits, spawned = hits + spawned_hits(extra, None), True
    hits = [h for h in hits if h["damages"]]
    return hits if spawned and hits != [{"kind": "projectile", "damages": own}] else None


def resolve_hits(items: list[dict], creatures: list[dict]) -> None:
    attacks = {a for c in creatures for a in c.get("attacks", [])}
    for i in items:
        if i["id"] in attacks and (h := attack_hits(i["id"])) is not None:
            i["hits"] = h or [{"kind": "none"}]  # spawns only creatures or effects: no damage


def has_no_icon(name: str) -> bool:
    """An internal attack item: never in an inventory, so nobody summons with it unless a creature carries it."""
    return not any(icon(i) for i in comp(PREFABS[name], "ItemDrop")["m_itemData"]["m_shared"]["m_icons"] or [])


def summon_spawns() -> list[dict]:
    """Creatures made by another's attack or a player's item: `summon` with the summoning `parent` creature (it
    carries the attack `item`) or just the `item` when no creature carries it (a staff)."""
    carried = defaultdict(list)
    for name, p in PREFABS.items():
        if is_creature(name):
            for i in carried_items(comp(p, "Humanoid") or comp(p, "Character")):
                carried[i].append(name)
    out = []
    for name in PREFABS:
        if is_item(name):
            for target in summoned_by(name):
                out += [{"creature": target, "source": "summon", "parent": parent, "item": name}
                        for parent in sorted(carried[name])] or [{"creature": target, "source": "summon", "item": name}
                                                                 for _ in [0] if not has_no_icon(name)]
    return out


def phase_spawns() -> list[dict]:
    """Boss phases: a creature whose death effects create another creature (FrozenKing -> FrozenKing_p2), or
    projectiles that spawn creatures where they land (FrozenKing's Aspects)."""
    out = []
    for name, p in PREFABS.items():
        if is_creature(name):
            c = comp(p, "Humanoid") or comp(p, "Character")
            for e in (c.get("m_deathEffects") or {}).get("m_effectPrefabs", []):
                if (nxt := ref(e["m_prefab"])) and nxt != name:
                    out += [{"creature": made, "source": "phase", "parent": name} for made in summoned_creatures(nxt)
                            if made != name]
    return out


def spawns() -> list[dict]:
    return world_spawns() + raid_spawns() + location_spawns() + offspring_spawns() + summon_spawns() + phase_spawns()


def piece_tools() -> dict[str, list[str]]:
    """piece id -> tools (item ids) whose build menu contains it."""
    table_tool = defaultdict(list)
    for name, p in PREFABS.items():
        if (d := comp(p, "ItemDrop")) and (t := ref(d["m_itemData"]["m_shared"]["m_buildPieces"])):
            table_tool[t].append(name)
    tools = defaultdict(list)
    for t in load("piece_tables.json"):
        for pc in t["fields"].get("m_pieces") or []:
            if ref(pc):
                tools[ref(pc)].extend(table_tool[t["name"]])
    return tools


# ---------------------------------------------------------------------------------------------


def write(name: str, data) -> None:
    data = prune(data)
    (OUT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {name}: {len(data) if isinstance(data, list) else 'ok'}")


def steam_build_id() -> str:
    """Steam build id of the dumped server: $MIMIR_STEAM_BUILDID (set by CI from scripts/steam-buildid.sh).
    Without it (local runs), keep the id already in meta.json; CI's next poll corrects a stale one."""
    if build := os.environ.get("MIMIR_STEAM_BUILDID", "").strip():
        return build
    old = OUT / "meta.json"
    return json.loads(old.read_text()).get("steamBuildId", "") if old.exists() else ""


def main(argv: list[str]) -> int:
    setup(argv[0] if argv else RAW, argv[1] if len(argv) > 1 else OUT)
    print(f"normalizing {RAW} -> {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    m = load("manifest.json")
    tools = piece_tools()
    defaults = {d["type"]: d["fields"] for d in load("status_effect_defaults.json")}

    items, creatures, pieces, procs, sources = [], [], [], [], []
    for name, p in PREFABS.items():
        if p["isItem"] and (i := item(name, p)):
            items.append(i)
        if c := creature(name, p):
            creatures.append(c)
        if pc := piece(name, p, tools):
            pieces.append(pc)
        procs.extend(processing(name, p))
        if not p["isItem"] and not has(p, "Piece") and (s := source(name, p)):
            sources.append(s)
    place_sources(sources)
    place_pieces(pieces)
    sources += location_containers()
    spawn_list = spawns()
    sources += fishing(spawn_list)
    sources += traders()

    prune_item_fields(items)
    resolve_hits(items, creatures)
    recipes = [recipe(r) for r in load("recipes.json")]
    seasons(pieces, recipes)
    mark_enemy_only(items, creatures, recipes, procs, sources, pieces)
    mark_unobtainable(items, creatures, pieces, recipes, procs, sources, spawn_list)
    data = {
        "items.json": items,
        "recipes.json": recipes,
        "creatures.json": creatures,
        "spawns.json": spawn_list,
        "pieces.json": pieces,
        "processing.json": sorted(procs, key=lambda x: (x["station"], x["from"], x["to"])),
        "sources.json": sources,
        "status_effects.json": [status_effect(e, defaults) for e in load("status_effects.json")],
    }
    for name, v in data.items():
        write(name, v)
    write("meta.json", {
        "gameVersion": m["gameVersion"], "networkVersion": m["networkVersion"], "dumperVersion": m["dumperVersion"],
        "steamBuildId": steam_build_id(),
        "counts": {k.removesuffix(".json"): len(v) for k, v in data.items()},
        "unresolvedTokens": sorted(unresolved),
        "skippedRefs": sorted(skipped_refs),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

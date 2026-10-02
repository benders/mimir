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
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".cache/dump/public/raw"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data"

TOKEN = re.compile(r"\$([A-Za-z0-9_]+)")
unresolved: set[str] = set()
skipped_refs: set[str] = set()  # references to prefabs that aren't items/creatures (projectiles, ambient fx)


def load(rel: str):
    return json.loads((RAW / rel).read_text(encoding="utf-8"))


TRANSLATIONS: dict[str, str] = load("localization/English.json")


def text(s: str | None) -> str | None:
    """Resolve $tokens to English, the way the game's Localization.Localize does."""
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

PREFABS: dict[str, dict] = {}
for f in sorted((RAW / "prefabs").glob("*.json")):
    p = json.loads(f.read_text(encoding="utf-8"))
    PREFABS[p["name"]] = p


def is_item(name: str | None) -> bool:
    return name in PREFABS and PREFABS[name]["isItem"]


def is_creature(name: str | None) -> bool:
    p = PREFABS.get(name)
    return p is not None and bool(comp(p, "Humanoid") or comp(p, "Character")) and not comp(p, "Player")


def keep(name: str | None, *preds) -> bool:
    """Whether a reference points at something the site shows; records the ones it drops."""
    if name is None:
        return False
    if any(p(name) for p in preds):
        return True
    skipped_refs.add(name)
    return False


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


def creature(name: str, p: dict) -> dict | None:
    c = comp(p, "Humanoid") or comp(p, "Character")
    if not c or comp(p, "Player"):
        return None
    attacks = set()
    for v in (c.get("m_defaultItems") or []) + (c.get("m_randomWeapon") or []):
        attacks.add(ref(v))
    for s in c.get("m_randomSets") or []:
        attacks.update(ref(v) for v in s["m_items"])
    attacks = {a for a in attacks if keep(a, is_item)}
    drops = [{
        "item": ref(d["m_prefab"]), "min": d["m_amountMin"], "max": d["m_amountMax"], "chance": d["m_chance"],
        "onePerPlayer": d["m_onePerPlayer"], "levelMultiplier": d["m_levelMultiplier"],
    } for d in (comp(p, "CharacterDrop") or {}).get("m_drops", []) if keep(ref(d["m_prefab"]), is_item, is_creature)]
    tame = comp(p, "Tameable")
    ai = comp(p, "MonsterAI") or comp(p, "AnimalAI") or {}
    return {
        "id": name,
        "name": text(c["m_name"]),
        "faction": c["m_faction"],
        "group": c["m_group"],
        "boss": c["m_boss"],
        "defeatKey": c.get("m_defeatSetGlobalKey"),
        "health": c["m_health"],
        "damageModifiers": modifiers(c["m_damageModifiers"]),
        "speed": {"walk": c["m_walkSpeed"], "run": c["m_runSpeed"], "swim": c["m_swimSpeed"] if c["m_canSwim"] else 0,
                  "fly": c["m_flyFastSpeed"] if c["m_flying"] else 0},
        "attacks": sorted(attacks),
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
        "dlc": pc["m_dlc"],
    }


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
    return [x for x in out if x["from"] and x["to"]]


def source(name: str, p: dict) -> dict | None:
    """World objects that yield items: pickables, ore veins, rocks, trees, logs, breakables."""
    entry: dict = {"id": name}
    if pk := comp(p, "Pickable"):
        entry.update(kind="pickable", name=text(pk["m_overrideName"]), pickable={
            "item": ref(pk["m_itemPrefab"]), "amount": pk["m_amount"], "respawnMinutes": pk["m_respawnTimeMinutes"]},
            drops=drop_table(pk["m_extraDrops"]))
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


def spawns() -> list[dict]:
    out = []
    for lst in sorted(load("world/SpawnSystemList.json"), key=lambda s: s["name"]):
        for s in lst["fields"]["m_spawners"]:
            if not s["m_enabled"] or s.get("m_devDisabled") or not keep(ref(s["m_prefab"]), is_creature, is_item):
                continue
            out.append({
                "creature": ref(s["m_prefab"]),
                "list": lst["name"],
                "biomes": [b for b in s["m_biome"].split(", ") if b != "None"],
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
            })
    return out


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


def main() -> int:
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
        if not p["isItem"] and not comp(p, "Piece") and (s := source(name, p)):
            sources.append(s)

    data = {
        "items.json": items,
        "recipes.json": [recipe(r) for r in load("recipes.json")],
        "creatures.json": creatures,
        "spawns.json": spawns(),
        "pieces.json": pieces,
        "processing.json": sorted(procs, key=lambda x: (x["station"], x["from"], x["to"])),
        "sources.json": sources,
        "status_effects.json": [status_effect(e, defaults) for e in load("status_effects.json")],
    }
    for name, v in data.items():
        write(name, v)
    write("meta.json", {
        "gameVersion": m["gameVersion"], "networkVersion": m["networkVersion"], "dumperVersion": m["dumperVersion"],
        "counts": {k.removesuffix(".json"): len(v) for k, v in data.items()},
        "unresolvedTokens": sorted(unresolved),
        "skippedRefs": sorted(skipped_refs),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())

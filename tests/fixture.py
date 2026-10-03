"""A tiny synthetic raw dump, in the plugin's output layout, for the normalize tests.

Every name and number here is invented: no game data is checked in. Builders fill in the fields
normalize.py reads with neutral defaults; keyword arguments override them (m_ prefix added).

    write_dump(Path("/tmp/raw"))   # manifest.json, prefabs/, recipes.json, localization/, ...
"""
import json
from pathlib import Path


def R(name):
    return {"$ref": name}


def S(name):
    return {"$sprite": name}


def m(**kw):
    return {f"m_{k}": v for k, v in kw.items()}


def comp(type_, fields, path=None):
    c = {"type": type_, "fields": fields}
    if path:
        c["path"] = path
    return c


def prefab(name, *components, is_item=False):
    return {"name": name, "isItem": is_item, "components": [comp("ZNetView", {}), *components]}


def with_components(p, *components):
    return {**p, "components": p["components"] + list(components)}


DAMAGES = {f"m_{k}": 0 for k in
           ("damage", "blunt", "slash", "pierce", "chop", "pickaxe", "fire", "frost", "lightning", "poison", "spirit")}


def damages(**kw):
    return {**DAMAGES, **m(**kw)}


def attack(**kw):
    return {**m(attackAnimation="swing", attackType="Horizontal", attackStamina=10, attackEitr=0, attackHealth=0,
                attackHealthPercentage=0, damageMultiplier=1, attackProjectile=None, projectiles=1), **m(**kw)}


def shared(**kw):
    return {**m(
        name="", description="", itemType="Material", icons=[], weight=1.0, value=0, maxStackSize=1, maxQuality=1,
        teleportable=True, dlc="", skillType="None", toolTier=0, damages=damages(), damagesPerLevel=damages(),
        attackForce=0, backstabBonus=1, armor=0, armorPerLevel=0, blockPower=0, blockPowerPerLevel=0,
        deflectionForce=0, deflectionForcePerLevel=0, timedBlockBonus=1, useDurability=False, maxDurability=100,
        durabilityPerLevel=50, useDurabilityDrain=1, canBeReparied=True, attack=attack(attackAnimation=""),
        secondaryAttack=attack(attackAnimation=""), ammoType="", food=0, foodStamina=0, foodEitr=0, foodBurnTime=0,
        foodRegen=0, isDrink=False, movementModifier=0, damageModifiers=[], equipStatusEffect=None,
        consumeStatusEffect=None, setName="", setSize=0, setStatusEffect=None, buildPieces=None), **m(**kw)}


def item(name, /, **kw):
    return prefab(name, comp("ItemDrop", {"m_itemData": {"m_shared": shared(**kw)}}), is_item=True)


def character(type_="Humanoid", **kw):
    return comp(type_, {**m(
        name="", faction="ForestMonsters", group="", boss=False, defeatSetGlobalKey="", health=100,
        damageModifiers={f"m_{k}": "Normal" for k in ("blunt", "slash", "pierce", "fire", "frost", "poison")},
        walkSpeed=2, runSpeed=5, swimSpeed=2, canSwim=True, flyFastSpeed=0, flying=False, defaultItems=[],
        randomWeapon=[], randomShield=[], randomArmor=[], randomSets=[], randomItems=[]), **m(**kw)})


def char_drop(item, **kw):
    return {**m(prefab=R(item), amountMin=1, amountMax=1, chance=1, onePerPlayer=False, levelMultiplier=True), **m(**kw)}


def req(item, amount=1, per_level=0, recover=True, upgrader=None):
    r = m(resItem=R(item), amount=amount, amountPerLevel=per_level, recover=recover)
    if upgrader is not None:
        r["m_upgraderResource"] = upgrader
    return r


def piece(name, /, *extra, **kw):
    return prefab(name, comp("Piece", {**m(
        name="", description="", icon=None, enabled=True, category="Misc", craftingStation=None, resources=[],
        comfort=0, comfortGroup="None", onlyInBiome="None", dlc=""), **m(**kw)}),
        comp("WearNTear", m(health=400, materialType="Wood", damages={"m_fire": "Weak", "m_chop": "Normal"})),
        *extra)


def drop_table(*drops, **kw):
    return {**m(dropMin=1, dropMax=1, dropChance=1, oneOfEach=False,
                drops=[m(item=R(i), stackMin=lo, stackMax=hi, weight=w) for i, lo, hi, w in drops]), **m(**kw)}


def recipe(name, item, station=None, level=1, resources=(), /, **kw):
    return {"name": name, "type": "Recipe", "fields": {**m(
        item=R(item), amount=1, enabled=True, craftingStation=R(station) if station else None,
        minStationLevel=level, repairStation=None, noCraftOnlyUpgrade=False, requireOnlyOneIngredient=False,
        resources=list(resources)), **m(**kw)}}


def spawner(creature, **kw):
    return {**m(prefab=R(creature), enabled=True, devDisabled=False, biome="Meadows", biomeArea="Everything",
                maxSpawned=2, spawnInterval=90, spawnChance=50, groupSizeMin=1, groupSizeMax=1, minLevel=1, maxLevel=3,
                spawnAtDay=True, spawnAtNight=True, minAltitude=0, maxAltitude=1000, requiredGlobalKey="",
                requiredEnvironments=[], huntPlayer=False), **m(**kw)}


def creature_spawner(creature, **kw):
    return {**m(creaturePrefab=R(creature), minLevel=1, maxLevel=1, respawnTimeMinuts=0), **m(**kw)}


def spawners(*components):
    """A location or room: game components, as children of the root object."""
    return [comp(t, f, path=f"child{i}") for i, (t, f) in enumerate(components)]


def container(*drops, name="$piece_chest"):
    return ("Container", {"m_name": name, **m(defaultItems=drop_table(*drops))})


def zone_location(name, biome, enable=True):
    return m(name=name, prefabName=name, enable=enable, biome=biome)


def event(name, biome, *spawns, **kw):
    return {**m(name=name, enabled=True, devDisabled=False, biome=biome, startMessage="$event_test",
                requiredGlobalKeys=[], notRequiredGlobalKeys=["defeated_chief"], spawn=list(spawns)), **m(**kw)}


SE_DEFAULTS = m(name="", tooltip="", icon=None, category="", ttl=0, cooldown=0, startMessage="", mods=[],
                healthRegenMultiplier=1, staminaRegenMultiplier=1, percentigeDamageModifiers=damages(),
                runStaminaDrainModifier=0)

TRANSLATIONS = {
    "piece_chest": "Strongbox",
    "item_wood": "Twig", "item_wood_desc": "A stick.",
    "item_ore": "Rustore", "item_ingot": "Ingot",
    "item_sword": "Test Sword", "item_sword_desc": "Sharp <b>enough</b>.",
    "item_helmet": "Pot Helm", "item_fish": "Glimfish", "item_pearl": "Moon Pearl", "item_mead": "Fizz Mead", "item_coins": "Coins", "item_charm": "Lucky Charm", "npc_vendor": "Old Vendor",
    "item_hammer": "Mallet", "item_bite": "Bite",
    "enemy_raider": "Raider", "piece_bench": "Bench", "piece_anvil": "Anvil", "piece_kiln": "Kiln",
    "piece_bush": "Twig Bush", "piece_orerock": "Ore Rock", "se_fizz": "Fizzy",
    "enemy_pup": "Pup", "enemy_chief_p2": "Chief Risen", "enemy_imp": "Imp", "item_rod": "Summoning Rod", "enemy_chief": "<color=orange>Chief</color>", "item_egg": "Egg", "item_nectar": "Nectar", "item_ichor": "Ichor", "item_dust": "Dust",
    "piece_hive": "Hive", "piece_tap": "Tap", "piece_wildhive": "Wild Hive", "event_test": "Something stirs",
}


def raider(name, **kw):
    return prefab(name,
                  character(**{**dict(name="$enemy_raider", health=150, defaultItems=[R("Bite"), R("FW_Helmet")],
                                      damageModifiers={"m_blunt": "Weak", "m_slash": "Normal", "m_fire": "Immune",
                                                       "m_spirit": "Ignore", "m_chop": "Ignore", "m_pickaxe": "Ignore"}),
                               **kw}),
                  comp("CharacterDrop", {"m_drops": [char_drop("Ore", amountMax=3, chance=0.5),
                                                      char_drop("vfx_Poof")]}),  # effect prefab: skipped ref
                  comp("Tameable", m(fedDuration=600, tamingTime=1800, commandable=True)),
                  comp("MonsterAI", m(consumeItems=[R("Fish")], afraidOfFire=True, avoidWater=False)),
                  comp("Procreation", m(offspring=R("Pup"))))


def prefabs():
    return [
        item("Wood", name="$item_wood", description="$item_wood_desc", icons=[S("Wood")], maxStackSize=50),
        item("Ore", name="$item_ore", icons=[S("Ore")], maxStackSize=30, teleportable=False),
        item("Ingot", name="$item_ingot", icons=[S("Ingot")], maxStackSize=30),
        item("Sword", name="$item_sword", description="$item_sword_desc", itemType="OneHandedWeapon",
             icons=[S("Sword"), S("Sword (gold)")], maxQuality=4, skillType="Swords",
             damages=damages(slash=30, fire=5), damagesPerLevel=damages(slash=6), blockPower=10,
             blockPowerPerLevel=0.5, useDurability=True, attack=attack(), movementModifier=-0.05,
             damageModifiers=[{"m_type": "Fire", "m_modifier": "Resistant"},
                              {"m_type": "Pierce", "m_modifier": "Normal"}],
             setName="tester", setSize=2, setStatusEffect=R("SE_Fizz")),
        item("Helmet", name="$item_helmet", itemType="Helmet", icons=[S("Helmet")], armor=4, armorPerLevel=2),
        item("HelmetFem", name="$item_helmet", itemType="Helmet", icons=[S("Helmet")], armor=5),  # "Pot Helm (female)"
        item("WoodOld", name="$item_wood", description="$item_wood_desc", icons=[S("Wood")], maxStackSize=50),  # copy
        item("FW_Helmet", name="$item_helmet", itemType="Helmet", icons=[S("Helmet")], armor=8),  # carried copy
        item("SP_Helmet", name="$item_helmet", itemType="Helmet", icons=[S("Helmet")]),  # unused copy
        item("SP_Sword", name="Other Sword", itemType="OneHandedWeapon", icons=[S("Sword")]),  # renamed: not a copy
        with_components(item("Fish", name="$item_fish", icons=[S("Fish")]),  # caught with Wood in the Ocean
                        comp("Fish", m(name="$item_fish", baits=[m(bait=R("Wood"), chance=1)],
                                       extraDrops=drop_table(("Pearl", 1, 2, 1))))),
        item("Pearl", name="$item_pearl", icons=[S("Pearl")]),  # only from fishing
        item("Mead", name="$item_mead", itemType="Consumable", icons=[S("Mead")], consumeStatusEffect=R("SE_Fizz")),
        item("Hammer", name="$item_hammer", itemType="Tool", icons=[S("Hammer")], buildPieces=R("_HammerTable")),
        item("Bite", name="$item_bite", itemType="OneHandedWeapon", attack=attack(attackStamina=0),
             damages=damages(pierce=12)),  # no icon: internal attack item
        item("Gem", name="$item_gem", icons=[S("Gem")]),  # unresolved name, only in a chest: reachable, so shown
        item("Coins", name="$item_coins", icons=[S("Coins")]),
        item("Charm", name="$item_charm", icons=[S("Charm")]),  # only sold by the vendor, for Coins
        item("Mystery", name="$item_missing"),  # unresolved token, no source: hidden
        item("OddBar", name="$item_oddbar", description="$item_oddbar_desc", icons=[S("Ingot")]),  # unresolved, craftable: shown as "Odd Bar"
        raider("Raider"),
        raider("Raider_sleeping"),  # identical copy: merged into Raider's page
        raider("Raider_Ranged", health=120),  # differs: "Raider (archer)"
        prefab("Pup", character(name="$enemy_pup", health=20), comp("Growup", m(grownPrefab=R("Raider")))),
        prefab("Chief", character(name="$enemy_chief", health=900, boss=True, deathEffects={"m_effectPrefabs": [
            {"m_prefab": R("vfx_Poof")}, {"m_prefab": R("Chief_p2")}]})),  # second phase: made when it dies
        prefab("Chief_p2", character(name="$enemy_chief_p2", health=1200, boss=True)),
        prefab("Imp", character(name="$enemy_imp", health=30)),  # only summoned, by the Rod
        item("Rod", name="$item_rod", itemType="OneHandedWeapon", icons=[S("Rod")],
             attack=attack(attackProjectile=R("RodBolt"))),
        prefab("RodBolt", comp("Projectile", m(spawnOnHit=R("RodSpawn"), randomSpawnOnHit=[]))),
        prefab("RodSpawn", comp("SpawnAbility", m(spawnPrefab=[R("Imp"), R("Wood")]))),  # a summon: creatures only
        prefab("Wisp", character(name="$enemy_missing", health=10)),  # unresolved name, never spawns: hidden
        with_components(item("Egg", name="$item_egg", icons=[S("Egg")]), comp("EggGrow", m(grownPrefab=R("Pup")))),
        prefab("Spawner_Raider", comp("CreatureSpawner", creature_spawner("Raider"))),
        prefab("Player", character(name="Player"), comp("Player", {})),
        piece("Bench", comp("CraftingStation", m(name="$piece_bench", rangeBuild=20, craftRequireRoof=True,
                                                 craftRequireFire=False)),
              name="$piece_bench", icon=S("Bench"), category="Crafting", resources=[req("Wood", 10)]),
        piece("piece_bench", name="$piece_bench", icon=S("Bench"), comfort=2),  # not buildable: "Bench (world)"
        piece("Anvil", comp("StationExtension", m(craftingStation=R("Bench"))),
              name="$piece_anvil", icon=S("Anvil"), category="Crafting", craftingStation=R("Bench"),
              resources=[req("Ingot", 4, recover=False)]),
        piece("Kiln", comp("Smelter", m(conversion=[m(**{"from": R("Ore"), "to": R("Ingot")}),
                                                    m(**{"from": R("Ore"), "to": None})],
                                        secPerProduct=30, fuelItem=R("Wood"), fuelPerProduct=2, maxOre=10)),
              name="$piece_kiln", icon=S("Kiln"), craftingStation=R("Bench"), resources=[req("Wood", 5)],
              comfort=1, comfortGroup="Fire"),
        item("Nectar", name="$item_nectar", icons=[S("Nectar")]),  # only from the Hive piece
        item("Ichor", name="$item_ichor", icons=[S("Ichor")]),  # only from the Tap piece, which needs a Root
        item("Dust", name="$item_dust", icons=[S("Dust")]),  # from Tap2, whose Root2 isn't in the world
        piece("Hive", comp("Beehive", m(honeyItem=R("Nectar"), secPerUnit=600, maxHoney=4, biome="Meadows, BlackForest")),
              name="$piece_hive", icon=S("Hive"), resources=[req("Wood", 10)]),
        piece("Tap", comp("SapCollector", m(spawnItem=R("Ichor"), secPerUnit=60, maxLevel=10, mustConnectTo=R("Root"))),
              name="$piece_tap", icon=S("Tap"), resources=[req("Wood", 4)]),
        piece("Tap2", comp("SapCollector", m(spawnItem=R("Dust"), secPerUnit=60, maxLevel=10, mustConnectTo=R("Root2"))),
              name="$piece_tap", icon=S("Tap"), resources=[req("Wood", 4)]),
        prefab("WildHive", comp("WearNTear", m(health=20, materialType="Wood", damages={"m_fire": "Weak"})),
               comp("DropOnDestroyed", m(dropWhenDestroyed=drop_table(("Wood", 1, 3, 1), ("Ore", 1, 1, 1))))),
        prefab("Bush", comp("Pickable", m(overrideName="$piece_bush", itemPrefab=R("Wood"), amount=2,
                                          respawnTimeMinutes=240, extraDrops=drop_table())),
               comp("HoverText", m(text="ignored, Pickable has a name"))),
        prefab("OreRock", comp("MineRock", m(name="$piece_orerock", health=50, minToolTier=2,
                                             damageModifiers={"m_chop": "Immune", "m_pickaxe": "Normal"},
                                             dropItems=drop_table(("Ore", 1, 2, 1), ("Wood", 1, 1, 0.25),
                                                                  ("vfx_Poof", 1, 1, 1), dropMax=3)))),
        prefab("Boulder", comp("MineRock", m(name="Boulder", health=50, minToolTier=0, damageModifiers={},
                                             dropItems=drop_table()))),  # yields nothing: not a source
        prefab("Stub", comp("Pickable", m(overrideName="$piece_bush", itemPrefab=R("Ore"), amount=1,
                                          respawnTimeMinutes=0, extraDrops=drop_table()))),
        piece("Sapling", comp("Plant", m(growTime=100, grownPrefabs=[R("Stub")])), name="$piece_bush",
              icon=S("Sapling"), resources=[req("Wood")]),
        prefab("vfx_Poof"),
    ]


def recipes():
    return [
        recipe("Recipe_Sword", "Sword", "Bench", 2, [req("Ingot", 4, 2), req("Wood", 2, 1),
                                                     req("Fish", 1, 1, upgrader=True)]),
        recipe("Recipe_Helmet", "Helmet", "Bench", resources=[req("Ingot", 2, 1)]),
        recipe("Recipe_Mead", "Mead", amount=3, resources=[req("Fish", 1)]),
        recipe("Recipe_OddBar", "OddBar", resources=[req("Wood", 1)]),
        recipe("Recipe_Rod", "Rod", resources=[req("Wood", 1)]),
    ]


def status_effects():
    return [{"name": "SE_Fizz", "type": "SE_Stats", "fields": {**SE_DEFAULTS, **m(
        name="$se_fizz", tooltip="Bubbly.", icon=S("Mead"), category="mead", ttl=300, startMessage="ignored",
        mods=[{"m_type": "Poison", "m_modifier": "Resistant"}], healthRegenMultiplier=1.5,
        percentigeDamageModifiers=damages(fire=0.1), runStaminaDrainModifier=0)}}]


def write_dump(raw: Path) -> Path:
    def dump(rel, data):
        f = raw / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1), encoding="utf-8")

    dump("manifest.json", {"gameVersion": "0.0.1", "networkVersion": 1, "dumperVersion": "test",
                           "generatedAt": "2000-01-01T00:00:00Z", "counts": {}, "warnings": []})
    dump("localization/English.json", TRANSLATIONS)
    for p in prefabs():
        dump(f"prefabs/{p['name']}.json", p)
    dump("recipes.json", recipes())
    dump("status_effects.json", status_effects())
    dump("status_effect_defaults.json", [{"name": "SE_Stats", "type": "SE_Stats", "fields": SE_DEFAULTS}])
    dump("piece_tables.json", [{"name": "_HammerTable", "type": "PieceTable",
                                "fields": {"m_pieces": [R("Bench"), R("Anvil"), R("Kiln"), R("Hive"), R("Tap"), R("Tap2")]}}])
    dump("world/SpawnSystemList.json", [{"name": "Spawns", "type": "SpawnSystemList", "fields": {"m_spawners": [
        spawner("Raider", biome="Meadows, BlackForest", minLevel=1, maxLevel=2, spawnAtDay=False),
        spawner("Raider", enabled=False),
        spawner("Raider", devDisabled=True),
        spawner("vfx_Poof"),
        spawner("Spawner_Raider", biome="-1"),  # places a spawner, everywhere
        spawner("Raider_sleeping", biome="Meadows"),  # shown on Raider's page
        spawner("Fish", biome="Ocean"),  # a fish: its biomes go into the fishing source
    ]}}])
    dump("world/RandEventSystem.json", [{"name": "_GameMain", "type": "RandEventSystem", "fields": {"m_events": [
        event("army_test", "Meadows, Swamp", spawner("Raider", biome="1023", minLevel=2, maxLevel=1), spawner("vfx_Poof")),
        event("army_off", "Meadows", spawner("Pup"), enabled=False),
    ]}}])
    dump("world/ZoneSystem.json", [{"name": "_GameMain", "type": "ZoneSystem", "fields": {"m_vegetation": [
        m(prefab=R("Root"), enable=True, biome="Mountain"), m(prefab=R("Root"), enable=True, biome="Swamp"),
        m(prefab=R("Root"), enable=False, biome="Plains"), m(prefab=R("Root2"), enable=False, biome="Plains"),
        m(prefab=R("Bush"), enable=True, biome="Meadows, Swamp"), m(prefab=R("Bush"), enable=True, biome="Meadows")],
        "m_locations": [
        zone_location("Camp", "Swamp"),
        zone_location("Camp", "Plains"),  # same prefab placed in a second biome
        zone_location("Lair", "Mountain"),
        zone_location("Ruin", "Meadows", enable=False),
        zone_location("Market", "Meadows"),
    ]}}])
    dump("locations/Camp.json", {"name": "Camp", "components": [comp("Location", {}), *spawners(
        ("CreatureSpawner", creature_spawner("Raider", minLevel=3, maxLevel=1)),  # swapped levels
        ("CreatureSpawner", creature_spawner("Raider", minLevel=1, maxLevel=2, respawnTimeMinuts=30)),
        ("SpawnArea", m(prefabs=[m(prefab=R("Pup"), weight=1, minLevel=1, maxLevel=1)])),
        ("CreatureSpawner", creature_spawner("vfx_Poof")),
        container(("Gem", 1, 1, 1), ("Wood", 2, 5, 3)),
        container(("Wood", 1, 1, 1), name="$piece_other"),  # unresolved name: its own source
        container(),  # empty default items: not a source
    )]})
    dump("locations/Lair.json", {"name": "Lair", "components": [comp("Location", {}), *spawners(
        ("OfferingBowl", m(bossPrefab=R("Chief"), bossItem=R("Ore"), bossItems=3)),
        ("DungeonGenerator", m(themes="Cave")),
    ), comp("MineRock", {}, path="cave/OreRock (2)"),
        comp("Piece", {}, path="cave/piece_bench (1)")]})  # a non-buildable piece standing in the location  # an instance of a source inside the location
    dump("locations/Ruin.json", {"name": "Ruin", "components": spawners(("CreatureSpawner", creature_spawner("Pup")),
                                                                    container(("Ore", 1, 1, 1)))})  # disabled location
    dump("locations/Market.json", {"name": "Market", "components": [comp("Location", {}), comp("Trader", {
        **m(name="$npc_vendor"), "m_items": [m(prefab=R("Charm"), stack=2, price=50, requiredGlobalKey="defeated_chief"),
                                             m(prefab=R("vfx_Poof"), stack=1, price=1, requiredGlobalKey="")]},
        path="Stall/Vendor")]})
    dump("room_themes.json", {"None": 0, "Crypt": 1, "Cave": 4})
    dump("rooms/cave_a.json", {"name": "cave_a", "theme": 5, "enabled": True,  # Crypt|Cave: used by Lair
                               "components": [*spawners(("CreatureSpawner", creature_spawner("Pup", maxLevel=2)),
                                                        container(("Gem", 1, 1, 1), ("Wood", 2, 5, 3))),
                                              comp("Destructible", {}, path="hall/WildHive")]})
    dump("rooms/cave_off.json", {"name": "cave_off", "theme": 4, "enabled": False,
                                 "components": spawners(("CreatureSpawner", creature_spawner("Raider")))})
    dump("rooms/crypt_a.json", {"name": "crypt_a", "theme": 1, "enabled": True,
                                "components": spawners(("CreatureSpawner", creature_spawner("Raider")),
                                                     container(("Ore", 1, 1, 1)))})  # theme doesn't match Lair
    return raw

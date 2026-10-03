"""Unit and golden-file tests for scripts/normalize.py, on the synthetic dump in fixture.py.

    python3 -m unittest discover -s tests                         # or: make test
    MIMIR_UPDATE_GOLDEN=1 python3 -m unittest tests/test_normalize.py   # rewrite tests/golden/ after a deliberate change
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
GOLDEN = TESTS / "golden"
sys.path.insert(0, str(TESTS))
import fixture  # noqa: E402

spec = importlib.util.spec_from_file_location("normalize", ROOT / "scripts/normalize.py")
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raw = fixture.write_dump(Path(cls.tmp.name) / "raw")
        cls.out = Path(cls.tmp.name) / "out"
        N.setup(cls.raw, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        N.unresolved.clear()
        N.skipped_refs.clear()


class Helpers(FixtureCase):
    def test_text_resolves_tokens(self):
        self.assertEqual(N.text("$item_wood"), "Twig")
        self.assertEqual(N.text("  A $item_ore lump "), "A Rustore lump")
        self.assertEqual(N.unresolved, set())

    def test_text_strips_rich_text(self):
        self.assertEqual(N.text("$enemy_chief"), "Chief")
        self.assertTrue(N.styled("$enemy_chief"))
        self.assertFalse(N.styled("$enemy_pup"))
        self.assertEqual(N.text("<b>bold</b> and <size=20>big</size>"), "bold and big")
        self.assertEqual(N.text("a <3 b"), "a <3 b")  # not a tag
        self.assertTrue(N.creature("Chief", N.PREFABS["Chief"])["named"])

    def test_text_keeps_and_records_unknown_tokens(self):
        self.assertEqual(N.text("$item_nope"), "$item_nope")
        self.assertEqual(N.unresolved, {"item_nope"})

    def test_text_empty(self):
        self.assertIsNone(N.text(None))
        self.assertIsNone(N.text(""))
        self.assertIsNone(N.text("   "))

    def test_ref_and_icon(self):
        self.assertEqual(N.ref({"$ref": "Wood"}), "Wood")
        self.assertEqual(N.ref({"$asset": "Mat"}), "Mat")
        self.assertIsNone(N.ref("Wood"))
        self.assertIsNone(N.ref(None))
        self.assertEqual(N.icon({"$sprite": "Sword (gold)"}), "Sword__gold_")
        self.assertIsNone(N.icon({"$ref": "Wood"}))

    def test_prune(self):
        self.assertEqual(N.prune({"a": 0, "b": 0.0, "c": False, "d": "", "e": [], "f": {}, "g": None,
                                  "h": {"x": 0}, "keep": 1, "t": True, "s": "x"}),
                         {"keep": 1, "t": True, "s": "x"})
        # list elements are pruned inside but never dropped, so ranges like [0, 1000] survive
        self.assertEqual(N.prune({"r": [0, 1000], "l": [{"a": 0, "b": 2}]}), {"r": [0, 1000], "l": [{"b": 2}]})

    def test_damage_maps(self):
        self.assertEqual(N.damages({"m_slash": 5, "m_fire": 0}), {"slash": 5})
        self.assertEqual(N.damages(None), {})
        self.assertEqual(N.modifiers({"m_fire": "Weak", "m_frost": "Normal"}), {"fire": "Weak"})
        self.assertEqual(N.modifier_list([{"m_type": "Fire", "m_modifier": "Resistant"},
                                          {"m_type": "Pierce", "m_modifier": "Normal"}]), {"fire": "Resistant"})

    def test_drop_table(self):
        self.assertIsNone(N.drop_table(None))
        self.assertIsNone(N.drop_table(fixture.drop_table()))
        t = N.drop_table(fixture.drop_table(("Ore", 1, 2, 1), ("vfx_Poof", 1, 1, 1), dropMax=3))
        self.assertEqual(t["max"], 3)
        self.assertEqual([d["item"] for d in t["items"]], ["Ore"])
        self.assertEqual(N.skipped_refs, {"vfx_Poof"})

    def test_requirements(self):
        r = N.requirements([fixture.req("Ingot", 4, 2, recover=False), fixture.req("Fish", upgrader=True),
                            {**fixture.req("x"), "m_resItem": None}])
        self.assertEqual([x["item"] for x in r], ["Ingot", "Fish"])
        self.assertTrue(r[0]["noRecover"])
        self.assertTrue(r[1]["upgrader"])

    def test_has_component_without_fields(self):
        p = fixture.prefab("P", fixture.comp("Player", {}), fixture.comp("Player", {"m_x": 1}, path="child"))
        self.assertTrue(N.has(p, "Player"))
        self.assertEqual(N.comp(p, "Player"), {})  # falsy: why has() exists
        self.assertFalse(N.has(fixture.prefab("Q", fixture.comp("Player", {}, path="child")), "Player"))


class Entities(FixtureCase):
    def test_item_fields(self):
        i = N.item("Sword", N.PREFABS["Sword"])
        self.assertEqual(i["name"], "Test Sword")
        self.assertEqual(i["variants"], ["Sword", "Sword__gold_"])
        self.assertFalse(i["internal"])
        self.assertEqual(i["damages"], {"slash": 30, "fire": 5})
        self.assertEqual(i["modifiers"], {"movement": -0.05})
        self.assertEqual(i["set"], {"name": "tester", "size": 2, "effect": "SE_Fizz"})
        self.assertEqual(i["durability"]["max"], 100)
        self.assertIsNone(i["secondaryAttack"])  # no animation = no attack

    def test_item_without_icon_is_internal(self):
        self.assertTrue(N.item("Bite", N.PREFABS["Bite"])["internal"])

    def test_item_fields_pruned_by_type(self):
        items = [N.item(n, N.PREFABS[n]) for n in ("Helmet", "Buckler", "Sword", "Mead", "Bite")]
        N.prune_item_fields(items)
        helmet, buckler, sword, mead, bite = items
        self.assertEqual(helmet["armor"], 4)
        self.assertNotIn("block", helmet)
        self.assertNotIn("armor", buckler)  # #7: shields don't count towards armor
        self.assertEqual((buckler["skill"], buckler["block"]), ("Blocking", 20))
        self.assertNotIn("backstab", buckler)
        self.assertNotIn("armor", sword)
        self.assertEqual(sword["skill"], "Swords")
        self.assertFalse({"armor", "block", "skill", "backstab", "attackForce", "parryBonus"} & mead.keys())
        self.assertIn("backstab", bite)  # internal attack items keep everything

    def test_adrenaline_fields(self):
        items = [N.item(n, N.PREFABS[n]) for n in ("Charm", "Buckler", "Sword", "Mead")]
        N.prune_item_fields(items)
        charm, buckler, sword, mead = items
        self.assertEqual(charm["adrenaline"], {"max": 40, "effect": "SE_Fizz"})
        self.assertNotIn("blockAdrenaline", charm)  # trinkets don't block
        self.assertEqual((buckler["blockAdrenaline"], buckler["parryAdrenaline"]), (3, 0))
        self.assertEqual((sword["attack"]["adrenaline"], sword["attack"]["useAdrenaline"]), (2, 0))
        self.assertIsNone(mead["adrenaline"])
        a = N.player()["adrenaline"]
        self.assertEqual((a["degen"], a["perfectDodge"], a["nonBlockDamage"]), ([[0, 2], [1, 3]], 4, -1))

    def test_anim_seconds(self):
        ev = [[0.2, "Speed", 2.0], [0.4, "Hit"], [0.6, "Speed", 0.5]]
        self.assertEqual(N.anim_seconds(ev, 0, 1.0, 1.0, 1.0), (0.2 + 0.4 / 2 + 0.4 / 0.5, 0.5))
        self.assertEqual(N.anim_seconds(ev, 0, 0.5, 1.0, 2.0), (0.2 / 2 + 0.3 / 4, 2.0))  # state speed multiplies
        self.assertEqual(N.anim_seconds(ev, 0.3, 0.5, 2.0, 1.0), (0.1, 2.0))  # events before start don't apply

    def test_attack_timing(self):
        sword = N.item("Sword", N.PREFABS["Sword"])["attack"]
        # swing0 stops at Chain (0.6): 0.2 + 0.4/2; its speed 2 carries into swing1 (state speed 2): 0.1/4 + 0.7/1
        self.assertEqual(sword["chain"], [{"time": 0.4, "hits": 1}, {"time": 0.725, "hits": 2}])
        self.assertEqual(sword["lastChainMultiplier"], 2)
        self.assertEqual(sword["cycle"], round(0.4 + 0.725 + 3 * N.HIT_FREEZE, 3))  # + the freeze per melee hit
        self.assertNotIn("chain", N.item("SP_Sword", N.PREFABS["SP_Sword"])["attack"])  # looping: no exit time
        self.assertNotIn("chain", N.item("Bite", N.PREFABS["Bite"])["attack"])  # creature attack: not the player's animator
        bow = N.item("Longbow", N.PREFABS["Longbow"])["attack"]
        self.assertEqual((bow["draw"], "cycle" in bow), (2.5, False))  # skill-dependent: mechanics.attack_cycle
        xbow = N.item("Arbal", N.PREFABS["Arbal"])["attack"]
        self.assertEqual((xbow["reload"], xbow["reloadDone"], "cycle" in xbow), (4, 1.0, False))
        javelin = N.item("Javelin", N.PREFABS["Javelin"])["attack"]
        self.assertTrue(javelin["thrown"])  # the projectile respawns the item: no repeatable cycle
        self.assertEqual((javelin["chain"], "cycle" in javelin), ([{"time": 1.0, "hits": 1}], False))

    def test_attack_hits(self):
        self.assertIsNone(N.attack_hits("Bite"))  # melee: the item's own damage
        self.assertEqual(N.attack_hits("Spit"), [{"kind": "area", "damages": {"poison": 9}}])  # the pool, not the bolt

    def test_creature_splits_attacks_and_equipment(self):
        c = N.creature("Raider", N.PREFABS["Raider"])
        self.assertEqual(c["attacks"], ["Bite"])
        self.assertEqual(c["equipment"], ["FW_Helmet"])
        self.assertEqual([d["item"] for d in c["drops"]], ["Ore"])
        self.assertIn("vfx_Poof", N.skipped_refs)
        self.assertEqual(c["tameable"]["food"], ["Fish"])

    def test_player_is_not_a_creature(self):
        self.assertIsNone(N.creature("Player", N.PREFABS["Player"]))
        self.assertFalse(N.is_creature("Player"))
        self.assertTrue(N.is_creature("Raider"))

    def test_station_extension(self):
        tools = N.piece_tools()
        a = N.piece("Anvil", N.PREFABS["Anvil"], tools)
        self.assertEqual((a["extends"], a["station"], a["tools"]), ("Bench", "Bench", ["Hammer"]))
        b = N.piece("Bench", N.PREFABS["Bench"], tools)
        self.assertIsNone(b["extends"])
        self.assertEqual(b["craftingStation"]["buildRange"], 20)

    def test_processing_skips_incomplete_and_duplicate_conversions(self):
        p = N.processing("Kiln", N.PREFABS["Kiln"])
        self.assertEqual([(x["from"], x["to"], x["fuel"]) for x in p], [("Ore", "Ingot", "Wood")])

    def test_sources(self):
        self.assertIsNone(N.source("Boulder", N.PREFABS["Boulder"]))  # yields nothing
        self.assertIsNone(N.source("Wood", N.PREFABS["Wood"]))
        bush = N.source("Bush", N.PREFABS["Bush"])
        self.assertEqual((bush["kind"], bush["name"], bush["pickable"]["item"]), ("pickable", "Twig Bush", "Wood"))
        rock = N.source("OreRock", N.PREFABS["OreRock"])
        self.assertEqual(rock["minToolTier"], 2)

    def test_destructible_source(self):
        hive = N.source("WildHive", N.PREFABS["WildHive"])  # a destroyable object that isn't a Piece
        self.assertEqual((hive["kind"], hive["health"], [d["item"] for d in hive["drops"]["items"]]),
                         ("destructible", 20, ["Wood", "Ore"]))

    def test_pickable_item_source(self):
        t = N.source("Treasure", N.PREFABS["Treasure"])  # one random item; a 0..0 stack is the item's own
        self.assertEqual((t["kind"], t["pickable"]), ("pickable", {"oneOf": [{"item": "Wood", "min": 2, "max": 4},
                                                                              {"item": "Ore"}]}))
        self.assertEqual(N.source("Gift", N.PREFABS["Gift"])["pickable"], {"item": "Ore", "amount": 3})
        self.assertEqual(N.picked_items(t), {"Wood", "Ore"})

    def test_place_sources(self):
        sources = {s["id"]: s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))}
        N.place_sources(list(sources.values()))
        self.assertEqual(sources["Bush"]["biomes"], ["Meadows", "Swamp"])  # enabled vegetation, merged
        self.assertEqual(sources["OreRock"]["locations"], [{"location": "Lair", "dungeon": False}])
        self.assertEqual(sources["WildHive"]["locations"], [{"location": "Lair", "dungeon": True}])  # via a room
        # inactive in Lair: never placed; but under a RandomSpawn ancestor it is, with or without a netview's own
        self.assertEqual(sources["Treasure"]["locations"], [{"location": "Lair", "dungeon": False}])
        self.assertNotIn("locations", sources["Gift"])  # disabled, RandomSpawn on itself
        self.assertEqual(sources["Stub"]["placedBy"], ["Sapling"])
        self.assertNotIn("biomes", sources["Stub"])

    def test_place_pieces(self):
        pieces = [N.piece(n, p, N.piece_tools()) for n, p in N.PREFABS.items() if N.has(p, "Piece")]
        N.place_pieces(pieces)
        by = {p["id"]: p for p in pieces}
        self.assertEqual(by["piece_bench"]["locations"], [{"location": "Lair", "dungeon": False}])
        self.assertNotIn("locations", by["Bench"])  # not placed
        self.assertNotIn("locations", by["Anvil"])

    def test_unplaced_sources_dont_count(self):
        items = [{"id": "Rock"}, {"id": "Seed"}]
        src = lambda i, **kw: {"id": i, "kind": "rock", "drops": {"items": [{"item": "Rock"}]}, **kw}
        self.assertEqual(N.reachable(items, [], [], [], [], [src("a")], [])[0], set())
        self.assertEqual(N.reachable(items, [], [], [], [], [src("a", biomes=["Meadows"])], [])[0], {"Rock"})
        stages = [src("log", becomes="stub"), {"id": "stub", "kind": "log", "drops": {"items": [{"item": "Seed"}]}}]
        self.assertEqual(N.reachable(items, [], [], [], [], stages, [])[0], set())
        stages[0]["locations"] = [{"location": "X", "dungeon": False}]
        self.assertEqual(N.reachable(items, [], [], [], [], stages, [])[0], {"Rock", "Seed"})  # a stage of a placed one

    def test_stages(self):
        src = lambda i, kind="rock", **kw: {"id": i, "kind": kind, **kw}
        drops = lambda *xs: {"items": [{"item": x} for x in xs]}
        items = [{"id": x} for x in ("Wood", "Ore", "Bar", "Sword", "Club", "Gem", "Coins", "Charm", "Chest", "Hammer",
                                      "Pebble")]
        items += [{"id": "Pick", "toolTier": 2, "damages": {"pickaxe": 10}}, {"id": "Axe", "toolTier": 3, "damages": {"chop": 9}}]
        pieces = [{"id": "bench", "enabled": True, "tools": ["Hammer"], "resources": [{"item": "Wood"}]},
                  {"id": "ext", "enabled": True, "tools": ["Hammer"], "extends": "bench", "resources": [{"item": "Bar"}]},
                  {"id": "smelter", "enabled": True, "tools": ["Hammer"], "resources": [{"item": "Wood"}]}]
        recipes = [{"item": "Hammer", "enabled": True, "resources": [{"item": "Wood"}]},
                   {"item": "Pick", "enabled": True, "station": "bench", "resources": [{"item": "Gem"}]},
                   {"item": "Axe", "enabled": True, "station": "bench", "resources": [{"item": "Wood"}]},
                   {"item": "Club", "enabled": True, "station": "bench", "resources": [{"item": "Wood"}]},
                   {"item": "Sword", "enabled": True, "station": "bench", "stationLevel": 2, "resources": [{"item": "Wood"}]}]
        procs = [{"station": "smelter", "from": "Ore", "to": "Bar"}]
        sources = [src("tree", "tree", biomes=["Meadows"], drops=drops("Wood")),
                   src("vein", biomes=["Meadows"], minToolTier=2, drops=drops("Ore"),  # the pick needs a Mountain gem
                       damageModifiers={"chop": "Immune"}),
                   src("chest", "container", locations=[{"location": "Peak"}], drops=drops("Gem")),
                   src("purse", "container", locations=[{"location": "Camp"}], drops=drops("Coins")),
                   src("wreck", "destructible", locations=[{"location": "Shore"}], drops=drops("Pebble")),
                   src("orb", "destructible", locations=[{"location": "Peak"}], startsEvent="Siege"),
                   {"id": "Vendor", "kind": "trader", "locations": [{"location": "Camp", "biomes": ["Meadows"]}],
                    "sells": [{"item": "Charm", "requiredKey": "defeated_boss"}],
                    "takes": [{"item": "Chest", "setsKey": "Quest1"}]}]
        creatures = [{"id": "Boss", "boss": True, "defeatKey": "defeated_boss", "drops": [{"item": "Chest"}]},
                     {"id": "Raider"}, {"id": "Ghost"}, {"id": "Giant"}, {"id": "Serpent"}]
        spawn_list = [{"creature": "Boss", "source": "location", "biomes": ["BlackForest"]},
                      {"creature": "Raider", "source": "raid", "biomes": ["Meadows"], "requiredGlobalKeys": ["defeated_boss"]},
                      {"creature": "Ghost", "source": "raid", "biomes": ["Meadows"], "requiredGlobalKeys": ["quest1"]},
                      {"creature": "Giant", "source": "world", "biomes": ["Meadows", "DeepNorth"], "requiredEvent": "siege"},
                      {"creature": "Serpent", "source": "world", "biomes": ["Ocean"]}]
        location_list = [{"id": "Peak", "biomes": ["Mountain"]}, {"id": "Camp", "biomes": ["Meadows"]},
                         {"id": "Shore", "biomes": ["Swamp", "Ocean"]}]
        args = items, creatures, pieces, recipes, procs, sources, spawn_list, location_list
        reach = tuple(set(d) for d in N.stages(*args))
        self.assertEqual(reach, N.reachable(*args[:-1]))  # the first pass: soft requirements don't count
        got = {k: N.STAGES[v] for d in N.stages(*args, reach=reach) for k, v in d.items()}
        self.assertEqual(got["Wood"], "Meadows")
        self.assertEqual(got["Club"], "Meadows")
        self.assertEqual(got["Ore"], "Mountain")  # Meadows rock, but only the Mountain pick can mine it
        self.assertEqual(got["Bar"], "Mountain")
        self.assertEqual(got["Sword"], "Mountain")  # bench level 2 needs the extension, which costs Bar
        self.assertEqual(got["Boss"], "BlackForest")
        self.assertEqual(got["Raider"], "Swamp")  # a boss's key opens the next stage
        self.assertEqual(got["Charm"], "Swamp")
        self.assertEqual(got["Ghost"], "BlackForest")  # the key comes from handing over the Boss's chest
        self.assertEqual(got["Giant"], "Mountain")  # its event starts when the orb on the Peak is destroyed
        self.assertEqual(got["Serpent"], "Meadows")  # the open sea counts from the start
        self.assertEqual(got["Pebble"], "Swamp")  # a shore location: Ocean next to land is that land's shore
        N.STAGE_OVERRIDES["Club"] = "Plains"
        try:
            got = N.stages(*args, reach=reach)[0]
            self.assertEqual(N.STAGES[got["Club"]], "Plains")
        finally:
            del N.STAGE_OVERRIDES["Club"]
        for e in items + creatures + pieces:
            e.pop("stage", None)
        N.mark_stages(*args)
        self.assertEqual({i["id"]: i.get("stage") for i in items}["Sword"], "Mountain")

    def test_effect_stages(self):
        items = [N.item(n, p) for n, p in N.PREFABS.items() if p["isItem"]]
        N.guardian_powers(items)
        by = {i["id"]: i for i in items}
        self.assertEqual(by["Shard"]["guardianPower"], "SE_Ward")  # the GuardStone's ItemStand takes it
        self.assertEqual(by["Bite"]["attackEffect"], "SE_Stun")
        by["Shard"]["stage"], by["Mead"]["stage"] = "Mountain", "Meadows"
        creatures = [{"id": "Raider", "attacks": ["Bite"], "stage": "Swamp"}]  # Bite is internal: its carrier counts
        effects = [{"id": x} for x in ("SE_Ward", "SE_Stun", "SE_Fizz", "SE_Wet")]
        N.effect_stages(effects, items, creatures)
        self.assertEqual([e.get("stage") for e in effects], ["Mountain", "Swamp", "Meadows", None])

    def test_offspring_egg_is_reached(self):
        items, spawn_list = [{"id": "Egg"}], [{"creature": "Egg", "source": "offspring", "parent": "Hen"}]
        spawn_list.append({"creature": "Hen", "source": "world"})
        self.assertIn("Egg", N.reachable(items, [{"id": "Hen"}], [], [], [], [], spawn_list)[0])
        self.assertNotIn("Egg", N.reachable(items, [{"id": "Hen"}], [], [], [], [], spawn_list[:1])[0])

    def test_summons_and_phases(self):
        # projectile -> SpawnAbility (a non-networked prefab, from subprefabs/), and the attack's prefab being the ability
        self.assertEqual(self.spawns("summon"), [{"creature": "Imp", "source": "summon", "item": "Rod"},
                                                 {"creature": "Sprite", "source": "summon", "item": "Wand"}])
        self.assertEqual(self.spawns("phase"), [{"creature": "Chief_p2", "source": "phase", "parent": "Chief"},
                                                {"creature": "Shade", "source": "phase", "parent": "Chief"}])  # death burst

    def test_alt_biome_spawns(self):
        alt = [s for s in self.spawns("world") if s.get("altBiome")]
        self.assertEqual([(s["creature"], s["altBiome"], s["biomes"]) for s in alt], [("Moth", "Moths", ["Meadows"])])

    def test_offering_of_a_group(self):
        lair = {s["creature"]: s for s in self.spawns("location") if s["location"] == "Lair"}
        self.assertEqual(lair["Singer"]["summon"], {"item": "Wood", "amount": 1})  # children named after a creature prefab

    def test_creature_piece_is_reached_when_buildable(self):
        creatures, pieces = [{"id": "Dummy"}], [{"id": "Dummy", "enabled": True, "tools": ["Hammer"], "resources": []}]
        self.assertEqual(N.reachable([], creatures, pieces, [], [], [], [])[1], {"Dummy"})
        self.assertEqual(N.reachable([], creatures, [{**pieces[0], "tools": []}], [], [], [], [])[1], set())

    def test_summon_and_phase_need_their_parent(self):
        items, creatures = [{"id": "Rod"}], [{"id": "Imp"}, {"id": "A"}, {"id": "B"}, {"id": "C"}]
        spawn_list = [{"creature": "Imp", "source": "summon", "item": "Rod"},
                      {"creature": "C", "source": "phase", "parent": "B"},
                      {"creature": "B", "source": "phase", "parent": "A"},
                      {"creature": "Imp", "source": "summon", "parent": "Imp2"}]
        reached = lambda sp: N.reachable(items, creatures, [], [], [], [], sp)[1]
        self.assertEqual(reached(spawn_list), set())
        self.assertEqual(reached(spawn_list + [{"creature": "A", "source": "world"}]), {"A", "B", "C"})  # chained phases
        recipes = [{"item": "Rod", "enabled": True, "resources": []}]
        self.assertEqual(N.reachable(items, creatures, [], recipes, [], [], spawn_list)[1], {"Imp"})

    def test_produces(self):
        hive = N.piece("Hive", N.PREFABS["Hive"], {})["produces"]
        self.assertEqual(hive, {"item": "Nectar", "secPerUnit": 600, "max": 4, "biomes": ["Meadows", "BlackForest"]})
        tap = N.piece("Tap", N.PREFABS["Tap"], {})["produces"]
        self.assertEqual((tap["item"], tap["connectsTo"]), ("Ichor", {"id": "Root", "biomes": ["Mountain", "Swamp"]}))
        self.assertEqual(N.piece("Tap2", N.PREFABS["Tap2"], {})["produces"]["connectsTo"], {"id": "Root2", "biomes": []})
        self.assertIsNone(N.piece("Bench", N.PREFABS["Bench"], {})["produces"])

    def test_status_effect_diffs_against_defaults(self):
        defaults = {d["type"]: d["fields"] for d in N.load("status_effect_defaults.json")}
        e = N.status_effect(N.load("status_effects.json")[0], defaults)
        self.assertEqual(e["name"], "Fizzy")
        self.assertEqual(e["duration"], 300)
        # changed gameplay fields only; presentation (startMessage, icon, name) never in stats
        self.assertEqual(set(e["stats"]), {"mods", "healthRegenMultiplier", "percentigeDamageModifiers"})
        self.assertEqual(e["stats"]["mods"], {"poison": "Resistant"})
        self.assertEqual(e["stats"]["percentigeDamageModifiers"], {"fire": 0.1})

    def test_biomes(self):
        self.assertEqual(N.biomes("Meadows, BlackForest"), ["Meadows", "BlackForest"])
        self.assertEqual(N.biomes("None"), [])
        self.assertEqual(N.biomes("10"), ["Swamp", "BlackForest"])
        self.assertEqual(len(N.biomes("-1")), len(N.BIOME_BITS))
        self.assertEqual(N.biomes("All"), N.biomes("-1"))

    def spawns(self, source):
        return [N.prune(s) for s in N.spawns() if s["source"] == source]

    def test_world_spawns(self):
        s = self.spawns("world")
        self.assertEqual(len(s), 6)  # disabled, devDisabled and non-creature spawners dropped; a fish is kept, so is the alt biome's Moth
        self.assertEqual([x["requiredEvent"] for x in s if x.get("requiredEvent")], ["siege"])
        self.assertEqual((s[0]["creature"], s[0]["biomes"]), ("Raider", ["Meadows", "BlackForest"]))
        self.assertEqual(s[1]["creature"], "Raider")  # placed via Spawner_Raider
        self.assertEqual(len(s[1]["biomes"]), len(N.BIOME_BITS))

    def test_raid_spawns(self):
        [r] = self.spawns("raid")  # disabled event and effect prefab dropped
        self.assertEqual((r["creature"], r["event"], r["message"]), ("Raider", "army_test", "Something stirs"))
        self.assertEqual(r["biomes"], ["Meadows", "Swamp"])  # the event's biome, not the spawner's
        self.assertEqual(r["levels"], [1, 2])

    def test_location_spawns(self):
        s = {(x["creature"], x["location"]): x for x in self.spawns("location")}
        self.assertEqual(set(s), {("Raider", "Camp"), ("Pup", "Camp"), ("Chief", "Lair"),
                          ("Raider", "Lair"), ("Pup", "Lair"), ("Singer", "Lair"), ("Raider_Ranged", "Stash")})  # Ruin disabled; Lair: a Spawner_ and a creature instance
        camp = s["Raider", "Camp"]
        self.assertEqual(camp["biomes"], ["Swamp", "Plains"])
        self.assertEqual(camp["levels"], [1, 3])  # merged; swapped min/max fixed
        self.assertTrue(camp["respawning"])
        self.assertEqual(s["Chief", "Lair"]["summon"], {"item": "Ore", "amount": 3})

    def test_dungeon_spawns(self):
        [d] = self.spawns("dungeon")  # Crypt room and disabled room don't match the Cave generator
        self.assertEqual((d["creature"], d["location"], d["biomes"], d["levels"]), ("Pup", "Lair", ["Mountain"], [1, 2]))

    def test_location_containers(self):
        by = {c["name"]: c for c in N.location_containers()}  # empty table dropped; one source per name + table
        self.assertEqual(set(by), {"Strongbox", "$piece_other", "Crate", "$piece_stash"})  # Crate: a placed prefab's Container
        box = by["Strongbox"]
        self.assertEqual(box["kind"], "container")
        self.assertEqual([d["item"] for d in box["drops"]["items"]], ["Gem", "Wood"])
        # in Camp and, as a dungeon room, in Lair; Ruin is disabled, the Crypt room's theme doesn't match Lair
        self.assertEqual([(x["location"], x["dungeon"]) for x in box["locations"]], [("Camp", False), ("Lair", True)])
        self.assertEqual(len({c["id"] for c in N.location_containers()}), 4)

    def test_fishing(self):
        [f] = N.fishing(N.spawns())
        self.assertEqual((f["id"], f["kind"], f["name"], f["biomes"]), ("Fish", "fishing", "Glimfish", ["Ocean"]))
        self.assertEqual(f["baits"], [{"item": "Wood", "chance": 1}])
        self.assertEqual([d["item"] for d in f["drops"]["items"]], ["Pearl"])

    def test_traders(self):
        [t] = N.traders()  # the id is the last path segment; the item-less vfx entry is skipped
        self.assertEqual((t["id"], t["kind"], t["name"]), ("Vendor", "trader", "Old Vendor"))
        self.assertEqual(t["sells"], [{"item": "Charm", "stack": 2, "price": 50, "requiredKey": "defeated_chief"}])
        self.assertEqual(t["locations"], [{"location": "Market", "biomes": ["Meadows"]}])

    def test_offspring(self):
        self.assertEqual([s["parent"] for s in self.spawns("offspring")], ["Raider", "Raider_Ranged", "Raider_sleeping"])
        self.assertEqual(self.spawns("egg"), [{"creature": "Pup", "source": "egg", "item": "Egg"}])
        self.assertEqual(self.spawns("growup"), [{"creature": "Raider", "source": "growup", "parent": "Pup"}])


class EnemyOnly(FixtureCase):
    def flags(self):
        items = [i for n, p in N.PREFABS.items() if p["isItem"] and (i := N.item(n, p))]
        creatures = [c for n, p in N.PREFABS.items() if (c := N.creature(n, p))]
        recipes = [N.recipe(r) for r in N.load("recipes.json")]
        procs = [x for n, p in N.PREFABS.items() for x in N.processing(n, p)]
        sources = [s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))]
        N.place_sources(sources)
        pieces = [x for n, p in N.PREFABS.items() if (x := N.piece(n, p, {}))]
        N.mark_enemy_only(items, creatures, recipes, procs, sources, pieces)
        return {i["id"] for i in items if i.get("enemyOnly")}

    def test_flags(self):
        flagged = self.flags()
        self.assertIn("FW_Helmet", flagged)    # carried by Raider, unobtainable
        self.assertIn("SP_Helmet", flagged)    # prefixed copy of craftable Helmet, same name
        self.assertNotIn("SP_Sword", flagged)  # different name: not a copy
        self.assertNotIn("Fish", flagged)      # unobtainable here, but not enemy gear
        self.assertNotIn("Bite", flagged)      # internal, handled separately
        self.assertNotIn("Helmet", flagged)


class Unobtainable(FixtureCase):
    def flagged(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"MIMIR_STEAM_BUILDID": "1"}):
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                N.main([str(self.raw), str(out)])
            entries = [e for f in ("items", "creatures", "pieces")
                       for e in json.loads((out / f"{f}.json").read_text(encoding="utf-8"))]
        N.setup(self.raw, self.out)
        return {e["id"] for e in entries if e.get("unobtainable")}

    def test_flags(self):
        flagged = self.flagged()
        self.assertIn("Wisp", flagged)       # never spawns
        self.assertIn("Dust", flagged)       # from a tap whose root isn't in the world
        self.assertNotIn("Mystery", flagged)  # internal (no icon): hidden already, not flagged twice
        self.assertNotIn("FW_Helmet", flagged)  # enemyOnly, likewise
        for x in ("Fish", "Chief", "Sword", "Gem", "Charm", "Shard", "Sapling", "Raider_Ranged"):
            self.assertNotIn(x, flagged)

    def test_reachable(self):
        items, creatures, pieces = (
            [x for n, p in N.PREFABS.items() if (x := f(n, p))]
            for f in (lambda n, p: p["isItem"] and N.item(n, p), N.creature, lambda n, p: N.piece(n, p, N.piece_tools())))
        recipes = [N.recipe(r) for r in N.load("recipes.json")]
        procs = [x for n, p in N.PREFABS.items() for x in N.processing(n, p)]
        sources = [s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))]
        N.place_sources(sources)
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources, N.spawns())  # without fishing
        self.assertTrue({"Wood", "Ore", "Ingot", "Sword", "Helmet"} <= got)  # source -> smelt -> craft (upgrader ignored)
        self.assertNotIn("Mead", got)  # needs Fish, which nothing yields
        self.assertNotIn("Gem", got)
        self.assertIn("Shard", got)  # the placed Altar breaks into it (m_spawnWhenDestroyed)
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources + N.location_containers(), N.spawns())
        self.assertIn("Gem", got)  # found in a chest
        fish = N.fishing(N.spawns())
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources + fish, N.spawns())
        self.assertTrue({"Fish", "Pearl", "Mead"} <= got)  # spawned, bait (Wood) reachable; its drop and dish follow
        shop = N.traders()
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources, N.spawns())
        self.assertNotIn("Charm", got)  # for sale, but Coins are unreachable
        coins = [{"id": "purse", "kind": "container", "drops": {"items": [{"item": "Coins"}]}}]
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources + shop, N.spawns())
        self.assertNotIn("Charm", got)
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources + coins + shop, N.spawns())
        self.assertIn("Charm", got)  # the global key is ignored
        self.assertTrue({"Nectar", "Ichor"} <= got)  # honey from a buildable hive, sap from one with a Root in the world
        self.assertNotIn("Dust", got)  # its Root2 isn't placed
        twin = [dict(c, drops=c["drops"] + [{"item": "Twin"}]) if c["id"] == "Raider" else c for c in creatures]
        twin.append({"id": "Twin", "drops": [{"item": "Mystery"}]})  # a creature dropped by a creature (a second phase)
        got, got_creatures, _ = N.reachable(items, twin, pieces, recipes, procs, sources, N.spawns())
        self.assertIn("Twin", got_creatures)
        self.assertIn("Mystery", got)
        no_bait = [dict(f, baits=[{"item": "Gem", "chance": 1}]) for f in fish]  # Gem is unreachable here
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources + no_bait, N.spawns())
        self.assertNotIn("Fish", got)


class Seasons(FixtureCase):
    def test_season(self):
        winter = {"name": "Winter", "start": [1, 12], "end": [6, 1]}
        pieces = [N.piece(n, p, N.piece_tools()) for n, p in N.PREFABS.items() if n in ("Tree", "Bench")]
        recipes = [N.recipe(r) for r in N.load("recipes.json") if r["name"] in ("Recipe_Hat", "Recipe_Helmet")]
        N.seasons(pieces, recipes)
        by = {x["id"]: x for x in pieces + recipes}
        self.assertEqual(by["Tree"]["season"], winter)
        self.assertEqual(by["Recipe_Hat"]["season"], winter)
        self.assertNotIn("season", by["Bench"])
        self.assertNotIn("season", by["Recipe_Helmet"])

    def test_reachable(self):
        items = [N.item(n, p) for n, p in N.PREFABS.items() if p["isItem"]]
        pieces = [x for n, p in N.PREFABS.items() if (x := N.piece(n, p, N.piece_tools()))]
        recipes = [N.recipe(r) for r in N.load("recipes.json")]
        sources = [s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))]
        N.place_sources(sources)
        args = (items, [], pieces, recipes, [], sources, [])
        got, _, got_pieces = N.reachable(*args)
        self.assertNotIn("Hat", got)  # disabled
        self.assertNotIn("Tree", got_pieces)
        N.seasons(pieces, recipes)
        got, _, got_pieces = N.reachable(*args)
        self.assertIn("Hat", got)  # its recipe is disabled, but seasonal
        self.assertIn("Tree", got_pieces)


class BuildId(FixtureCase):
    def test_env_wins(self):
        with mock.patch.dict(os.environ, {"MIMIR_STEAM_BUILDID": " 42 "}):
            self.assertEqual(N.steam_build_id(), "42")

    def test_carried_over_from_meta(self):
        with mock.patch.dict(os.environ, {"MIMIR_STEAM_BUILDID": ""}):
            self.out.mkdir(parents=True, exist_ok=True)
            (self.out / "meta.json").write_text('{"steamBuildId": "7"}')
            try:
                self.assertEqual(N.steam_build_id(), "7")
            finally:
                (self.out / "meta.json").unlink()
            self.assertEqual(N.steam_build_id(), "")


class Golden(unittest.TestCase):
    """normalize.main on the fixture must reproduce tests/golden/ exactly (and be deterministic)."""

    def test_golden(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"MIMIR_STEAM_BUILDID": "1"}):
            raw = fixture.write_dump(Path(tmp) / "raw")
            out = Path(tmp) / "out"
            with mock.patch("sys.stdout"):
                self.assertEqual(N.main([str(raw), str(out)]), 0)
            got = {f.name: f.read_text(encoding="utf-8") for f in sorted(out.glob("*.json"))}
        if os.environ.get("MIMIR_UPDATE_GOLDEN"):
            GOLDEN.mkdir(exist_ok=True)
            for f in GOLDEN.glob("*.json"):
                f.unlink()
            for name, body in got.items():
                (GOLDEN / name).write_text(body, encoding="utf-8")
            self.skipTest("golden files rewritten")
        want = {f.name: f.read_text(encoding="utf-8") for f in sorted(GOLDEN.glob("*.json"))}
        self.assertEqual(sorted(got), sorted(want), "output files differ from tests/golden/")
        for name in want:
            with self.subTest(file=name):
                self.assertEqual(json.loads(got[name]), json.loads(want[name]))
                self.assertEqual(got[name], want[name])  # formatting too: data/ diffs must stay readable


if __name__ == "__main__":
    unittest.main()

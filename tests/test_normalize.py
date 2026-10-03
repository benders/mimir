"""Unit and golden-file tests for scripts/normalize.py, on the synthetic dump in fixture.py.

    python3 -m unittest discover -s tests                         # or: make test
    MIMIR_UPDATE_GOLDEN=1 python3 -m unittest tests/test_normalize.py   # rewrite tests/golden/ after a deliberate change
"""
import importlib.util
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

    def test_processing_skips_incomplete_conversions(self):
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
        self.assertEqual(len(s), 4)  # disabled, devDisabled and non-creature spawners dropped; a fish is kept
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
        self.assertEqual(set(s), {("Raider", "Camp"), ("Pup", "Camp"), ("Chief", "Lair")})  # Ruin disabled
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
        self.assertEqual(set(by), {"Strongbox", "$piece_other"})
        box = by["Strongbox"]
        self.assertEqual(box["kind"], "container")
        self.assertEqual([d["item"] for d in box["drops"]["items"]], ["Gem", "Wood"])
        # in Camp and, as a dungeon room, in Lair; Ruin is disabled, the Crypt room's theme doesn't match Lair
        self.assertEqual([(x["location"], x["dungeon"]) for x in box["locations"]], [("Camp", False), ("Lair", True)])
        self.assertEqual(len({c["id"] for c in N.location_containers()}), 2)

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
        items = [i for n, p in N.PREFABS.items() if p["isItem"] and (i := N.item(n, p))]
        creatures = [c for n, p in N.PREFABS.items() if (c := N.creature(n, p))]
        pieces = [x for n, p in N.PREFABS.items() if (x := N.piece(n, p, N.piece_tools()))]
        recipes = [N.recipe(r) for r in N.load("recipes.json")]
        procs = [x for n, p in N.PREFABS.items() for x in N.processing(n, p)]
        sources = [s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))]
        N.mark_unobtainable(items, creatures, pieces, recipes, procs, sources, N.spawns())
        return {e["id"] for e in items + creatures + pieces if e.get("unobtainable")}

    def test_flags(self):
        flagged = self.flagged()
        self.assertIn("Mystery", flagged)  # unresolved name, no source
        self.assertIn("Wisp", flagged)     # unresolved name, never spawns
        self.assertNotIn("Fish", flagged)  # a real name
        self.assertNotIn("Chief", flagged)
        self.assertNotIn("Sword", flagged)

    def test_reachable(self):
        items, creatures, pieces = (
            [x for n, p in N.PREFABS.items() if (x := f(n, p))]
            for f in (lambda n, p: p["isItem"] and N.item(n, p), N.creature, lambda n, p: N.piece(n, p, N.piece_tools())))
        recipes = [N.recipe(r) for r in N.load("recipes.json")]
        procs = [x for n, p in N.PREFABS.items() for x in N.processing(n, p)]
        sources = [s for n, p in N.PREFABS.items() if not p["isItem"] and (s := N.source(n, p))]
        got, _, _ = N.reachable(items, creatures, pieces, recipes, procs, sources, N.spawns())  # without fishing
        self.assertTrue({"Wood", "Ore", "Ingot", "Sword", "Helmet"} <= got)  # source -> smelt -> craft (upgrader ignored)
        self.assertNotIn("Mead", got)  # needs Fish, which nothing yields
        self.assertNotIn("Gem", got)
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

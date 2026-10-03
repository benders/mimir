"""Smoke test for scripts/build-site.py: build the site from tests/golden/ (no icons) and check its shape.
build-site.py itself fails on any broken internal link."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "site"
        cls.build = subprocess.run(
            [sys.executable, ROOT / "scripts/build-site.py", ROOT / "tests/golden", Path(cls.tmp.name) / "no-icons",
             cls.out], capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_builds(self):
        self.assertEqual(self.build.returncode, 0, self.build.stdout + self.build.stderr)

    def test_pages(self):
        for page in ("index.html", "items/Sword.html", "creatures/Raider.html", "pieces/Anvil.html",
                     "effects/SE_Fizz.html", "search.json", "style.css", "search.js"):
            self.assertTrue((self.out / page).is_file(), page)

    def test_hidden_items_have_no_page(self):
        for item in ("Bite", "FW_Helmet", "SP_Helmet"):
            self.assertFalse((self.out / f"items/{item}.html").exists(), item)
        self.assertTrue((self.out / "items/SP_Sword.html").exists())

    def test_relations(self):
        sword = (self.out / "items/Sword.html").read_text(encoding="utf-8")
        self.assertIn("Test Sword", sword)
        self.assertIn('href="pieces/Bench.html"', sword)  # crafted at
        ingot = (self.out / "items/Ingot.html").read_text(encoding="utf-8")
        self.assertIn('href="pieces/Kiln.html"', ingot)  # smelted in
        self.assertIn('href="items/Sword.html"', ingot)  # used in

    def test_seasonal(self):
        tree = (self.out / "pieces/Tree.html").read_text(encoding="utf-8")
        self.assertIn("Seasonal: Winter (1 Dec – 6 Jan)", tree)  # a normal page, with the season
        hat = (self.out / "items/Hat.html").read_text(encoding="utf-8")
        self.assertIn("Seasonal: Winter (1 Dec – 6 Jan)", hat)  # on the crafted item too
        self.assertNotIn("Seasonal", (self.out / "items/Sword.html").read_text(encoding="utf-8"))

    def test_producers(self):
        nectar = (self.out / "items/Nectar.html").read_text(encoding="utf-8")
        self.assertIn('href="pieces/Hive.html"', nectar)  # made by a placed piece
        self.assertIn("10 min each, up to ×4", nectar)
        hive = (self.out / "pieces/Hive.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Produces</h2>", hive)
        self.assertIn('href="items/Nectar.html"', hive)
        self.assertIn("Root", (self.out / "pieces/Tap.html").read_text(encoding="utf-8"))
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        self.assertIn('href="creatures/Pup.html"', raider)  # born from: grows up from Pup

    def test_spawn_sections(self):
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        for h in ("Spawns", "Locations", "Raids"):
            self.assertIn(f"<h2>{h}</h2>", raider)
        self.assertIn("Something stirs", raider)
        pup = (self.out / "creatures/Pup.html").read_text(encoding="utf-8")
        self.assertIn("in the dungeon", pup)
        self.assertIn("<h2>Born from</h2>", pup)
        self.assertIn('href="creatures/Raider.html"', pup)
        self.assertIn('href="items/Egg.html"', pup)
        chief = (self.out / "creatures/Chief.html").read_text(encoding="utf-8")
        self.assertIn("summoned with", chief)
        self.assertIn('href="items/Ore.html"', chief)

    def test_summon_and_phase_sections(self):
        imp = (self.out / "creatures/Imp.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Summoned by</h2>", imp)
        self.assertIn('href="items/Rod.html"', imp)
        phase = (self.out / "creatures/Chief_p2.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Phase of</h2>", phase)
        self.assertIn('href="creatures/Chief.html"', phase)

    def test_alt_biome_spawn_and_summons_through_abilities(self):
        moth = (self.out / "creatures/Moth.html").read_text(encoding="utf-8")
        self.assertIn("in Moths patches", moth)
        sprite = (self.out / "creatures/Sprite.html").read_text(encoding="utf-8")  # the Wand's ability makes it
        self.assertIn('href="items/Wand.html"', sprite)
        shade = (self.out / "creatures/Shade.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Phase of</h2>", shade)

    def test_container_found_in(self):
        gem = (self.out / "items/Gem.html").read_text(encoding="utf-8")  # unresolved name, only in a chest
        self.assertIn("<h2>Found in</h2>", gem)
        self.assertIn("Strongbox", gem)
        self.assertIn("Camp, Lair dungeon", gem)
        self.assertFalse((self.out / "items/Mystery.html").exists())

    def test_world_source_placement(self):
        ore = (self.out / "items/Ore.html").read_text(encoding="utf-8")  # mined from OreRock, placed in the Lair
        self.assertIn("Lair", ore)
        wood = (self.out / "items/Wood.html").read_text(encoding="utf-8")  # picked from a Bush in the Meadows and Swamp
        self.assertIn("Meadows, Swamp", wood)

    def test_random_pickable_found_in(self):
        ore = (self.out / "items/Ore.html").read_text(encoding="utf-8")  # one of Treasure's items, in Lair via RandomSpawn
        self.assertIn("Treasure", ore)
        self.assertIn("one of 2: ×1", ore)
        wood = (self.out / "items/Wood.html").read_text(encoding="utf-8")
        self.assertIn("one of 2: ×2–4", wood)

    def test_piece_found_in(self):
        bench = (self.out / "pieces/piece_bench.html").read_text(encoding="utf-8")  # world copy, placed in the Lair
        self.assertIn("<h2>Found in</h2>", bench)
        self.assertIn("Lair", bench)

    def test_sold_by(self):
        charm = (self.out / "items/Charm.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Sold by</h2>", charm)
        self.assertIn("Old Vendor", charm)
        self.assertIn('href="items/Coins.html"', charm)  # the price
        self.assertIn("×50", charm)
        self.assertIn("for ×2", charm)  # stack size
        self.assertIn("<th>After</th><", charm)
        self.assertIn("<td>defeated_chief</td>", charm)  # no boss sets this key: shown as is
        self.assertIn("Market (Meadows)", charm)

    def test_fishing(self):
        fish = (self.out / "items/Fish.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Fishing</h2>", fish)
        self.assertIn("Caught with", fish)
        self.assertIn('href="items/Wood.html"', fish)  # the bait
        self.assertIn("in Ocean", fish)
        wood = (self.out / "items/Wood.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Bait for</h2>", wood)
        self.assertIn('href="items/Fish.html"', wood)
        pearl = (self.out / "items/Pearl.html").read_text(encoding="utf-8")  # extra drop of a catch
        self.assertIn("Glimfish", pearl)
        self.assertIn("fishing", pearl)

    def test_unobtainable_hidden(self):
        for page in ("items/Mystery.html", "creatures/Wisp.html"):
            self.assertFalse((self.out / page).exists(), page)
        index = (self.out / "search.json").read_text(encoding="utf-8")
        self.assertNotIn("Mystery", index)
        self.assertNotIn("Wisp", index)

    def test_unresolved_name_fallback(self):
        bar = (self.out / "items/OddBar.html").read_text(encoding="utf-8")
        self.assertIn("<h1>Odd Bar</h1>", bar)
        self.assertNotIn("$item_oddbar", bar)

    def test_ignore_modifiers(self):
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        self.assertIn("<span>spirit</span>Immune", raider)
        self.assertNotIn("<span>chop</span>", raider)
        self.assertNotIn("<span>pickaxe</span>", raider)
        self.assertNotIn("Ignore", raider)

    def test_creatures_by_biome(self):
        index = (self.out / "creatures/index.html").read_text(encoding="utf-8")
        heads = re.findall(r'<h2 id="(\w+)">', index)
        self.assertEqual(heads, ["Meadows", "Mountain", "Other"])  # progression order; empty biomes left out
        mountain = index[index.index('id="Mountain"'):]
        self.assertLess(mountain.index("Chief"), mountain.index("Pup"))  # bosses first
        # Raider: world spawns in Meadows/Black Forest tie with a location in Swamp/Plains; earliest wins
        self.assertIn("creatures/Raider.html", index[:index.index('id="Mountain"')])
        pup = (self.out / "creatures/Pup.html").read_text(encoding="utf-8")
        self.assertRegex(pup, r"<dt>Biome</dt><dd>Swamp, Mountain, Plains</dd>")  # dungeon outweighs the camp
        self.assertRegex(pup, r"<dt>Faction</dt><dd>Forest monsters</dd>")

    def test_variants(self):
        # identical copies merge into one page; links and spawns go there
        self.assertFalse((self.out / "creatures/Raider_sleeping.html").exists())
        self.assertFalse((self.out / "items/WoodOld.html").exists())
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        self.assertIn("as sleeping", raider)
        self.assertIn("<h1>Raider</h1>", raider)
        # the rest get a qualifier from their ids
        ranged = (self.out / "creatures/Raider_Ranged.html").read_text(encoding="utf-8")
        self.assertIn("<h1>Raider (archer)</h1>", ranged)
        self.assertIn('9 poison <span class="qty">area</span>', ranged)  # the Spit's pool, not the item's 5 poison
        self.assertIn("<td>Spit</td>", ranged)  # internal attacks are named from their ids, not the shared placeholder
        self.assertEqual(ranged.count("<td>Bite</td>"), 1)
        self.assertIn("<h1>Pot Helm (female)</h1>", (self.out / "items/HelmetFem.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Pot Helm</h1>", (self.out / "items/Helmet.html").read_text(encoding="utf-8"))
        names = [e[0] for e in json.loads((self.out / "search.json").read_text(encoding="utf-8"))]
        self.assertEqual(names.count("Raider"), 1)
        self.assertIn("Raider (archer)", names)
        self.assertIn("<h1>Bench</h1>", (self.out / "pieces/Bench.html").read_text(encoding="utf-8"))  # buildable
        self.assertIn("<h1>Bench (world)</h1>", (self.out / "pieces/piece_bench.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Chief</h1>", (self.out / "creatures/Chief.html").read_text(encoding="utf-8"))

    def test_mechanics_section(self):
        for page in ("index", "blocking", "drops", "creature-levels", "damage-types", "item-upgrades", "adrenaline"):
            self.assertTrue((self.out / f"mechanics/{page}.html").is_file(), page)
        home = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn('<a href="mechanics/index.html">Mechanics</a>', home)  # nav entry
        self.assertIn('<a class="brand" href="index.html">Mimir&#x27;s Well</a>', home)
        self.assertIn("<h1>Mimir&#x27;s Well</h1>", home)
        index = (self.out / "mechanics/index.html").read_text(encoding="utf-8")
        for page in ("blocking", "drops", "creature-levels", "damage-types"):
            self.assertIn(f'href="mechanics/{page}.html"', index)
        self.assertFalse((self.out / "mechanics/blocking.md").exists())
        blocking = (self.out / "mechanics/blocking.html").read_text(encoding="utf-8")
        self.assertIn("Humanoid.BlockAttack", blocking)
        version = json.loads((ROOT / "tests/golden/meta.json").read_text(encoding="utf-8"))["gameVersion"]
        self.assertIn(f"decompiled game code of Valheim {version}", blocking)
        names = [e[0] for e in json.loads((self.out / "search.json").read_text(encoding="utf-8"))]
        self.assertIn("Blocking", names)

    def test_charts(self):
        for page, text in (("damage-types", "Damage taken against armor"), ("blocking", "Damage through a block"),
                           ("creature-levels", "Multipliers by star level")):
            html = (self.out / f"mechanics/{page}.html").read_text(encoding="utf-8")
            self.assertIn('<svg class="chart"', html)
            self.assertIn("<title", html)
            self.assertIn(text, html)

    def test_links_to_mechanics(self):
        items = list((self.out / "items").glob("*.html"))
        buckler = (self.out / "items/Buckler.html").read_text(encoding="utf-8")  # shield stats link to Blocking
        self.assertIn('href="mechanics/blocking.html"', buckler)
        self.assertIn("Test Buckler", (self.out / "mechanics/blocking.html").read_text(encoding="utf-8"))  # shields table
        dropped = [f for f in items if "<h2>Dropped by</h2>" in f.read_text(encoding="utf-8")]
        self.assertTrue(dropped)
        self.assertIn('href="mechanics/drops.html"', dropped[0].read_text(encoding="utf-8"))
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        self.assertIn('href="mechanics/creature-levels.html"', raider)
        self.assertIn('href="mechanics/damage-types.html"', raider)  # Resistances section
        self.assertIn('href="mechanics/drops.html"', raider)         # Drops section

    def test_adrenaline(self):
        charm = (self.out / "items/Charm.html").read_text(encoding="utf-8")
        self.assertIn("<dt>Max adrenaline</dt><dd>+40</dd>", charm)
        self.assertIn('<dt>When adrenaline is full</dt><dd><a class="ref" href="effects/SE_Fizz.html"', charm)
        self.assertIn('href="mechanics/adrenaline.html"', charm)
        self.assertIn("full adrenaline", (self.out / "effects/SE_Fizz.html").read_text(encoding="utf-8"))
        self.assertIn("+3 per block, +0 per parry", (self.out / "items/Buckler.html").read_text(encoding="utf-8"))
        page = (self.out / "mechanics/adrenaline.html").read_text(encoding="utf-8")
        self.assertIn("Adrenaline decay", page)  # chart
        self.assertIn('<td><a class="ref" href="items/Charm.html"', page)  # trinkets table
        self.assertIn("<td>Perfect dodge</td><td>4</td>", page)  # from player.json
        self.assertIn("<td>primary</td><td>Horizontal</td><td>2</td>", page)  # Sword: 2 per hit
        self.assertIn("<td>3</td><td>0</td>", page)  # Buckler's block and parry adrenaline

    def test_destroyed_into_item(self):
        shard = (self.out / "items/Shard.html").read_text(encoding="utf-8")
        self.assertIn("when destroyed", shard)

    def test_no_inverted_ranges(self):
        wood = (self.out / "items/Wood.html").read_text(encoding="utf-8")
        self.assertIn("<td>2</td>", wood)  # stackMin 2, stackMax 1 rolls Random.Range(2, 2)
        for page in self.out.rglob("*.html"):
            for lo, hi in re.findall(r"(?<![\d.])(\d+)–(\d+)(?![\d.])", page.read_text(encoding="utf-8")):
                self.assertLess(int(lo), int(hi), f"{page.name}: {lo}–{hi}")

    def test_search_index(self):
        index = json.loads((self.out / "search.json").read_text(encoding="utf-8"))
        names = {e[1] for e in index}
        self.assertIn("Sword", names)
        self.assertNotIn("FW_Helmet", names)
        self.assertTrue(all(len(e) == 5 for e in index))


if __name__ == "__main__":
    unittest.main()

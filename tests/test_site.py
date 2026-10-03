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

    def test_container_found_in(self):
        gem = (self.out / "items/Gem.html").read_text(encoding="utf-8")  # unresolved name, only in a chest
        self.assertIn("<h2>Found in</h2>", gem)
        self.assertIn("Strongbox", gem)
        self.assertIn("Camp, Lair dungeon", gem)
        self.assertFalse((self.out / "items/Mystery.html").exists())

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
        self.assertIn("<h1>Raider (archer)</h1>", (self.out / "creatures/Raider_Ranged.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Pot Helm (female)</h1>", (self.out / "items/HelmetFem.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Pot Helm</h1>", (self.out / "items/Helmet.html").read_text(encoding="utf-8"))
        names = [e[0] for e in json.loads((self.out / "search.json").read_text(encoding="utf-8"))]
        self.assertEqual(names.count("Raider"), 1)
        self.assertIn("Raider (archer)", names)
        self.assertIn("<h1>Bench</h1>", (self.out / "pieces/Bench.html").read_text(encoding="utf-8"))  # buildable
        self.assertIn("<h1>Bench (world)</h1>", (self.out / "pieces/piece_bench.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Chief</h1>", (self.out / "creatures/Chief.html").read_text(encoding="utf-8"))

    def test_search_index(self):
        index = json.loads((self.out / "search.json").read_text(encoding="utf-8"))
        names = {e[1] for e in index}
        self.assertIn("Sword", names)
        self.assertNotIn("FW_Helmet", names)
        self.assertTrue(all(len(e) == 5 for e in index))


if __name__ == "__main__":
    unittest.main()

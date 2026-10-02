"""Smoke test for scripts/build-site.py: build the site from tests/golden/ (no icons) and check its shape.
build-site.py itself fails on any broken internal link."""
import json
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

    def test_search_index(self):
        index = json.loads((self.out / "search.json").read_text(encoding="utf-8"))
        names = {e[1] for e in index}
        self.assertIn("Sword", names)
        self.assertNotIn("FW_Helmet", names)
        self.assertTrue(all(len(e) == 5 for e in index))


if __name__ == "__main__":
    unittest.main()

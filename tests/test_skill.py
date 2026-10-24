"""The Claude skill (skills/mimir, #84): its script against a site built from tests/golden/, and the published zip."""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills/mimir"
spec = importlib.util.spec_from_file_location("mimir_skill", SKILL / "scripts/mimir.py")
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)


class Skill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = Path(cls.tmp.name) / "site"
        build = subprocess.run([sys.executable, ROOT / "scripts/build-site.py", ROOT / "tests/golden",
                                Path(cls.tmp.name) / "no-icons", cls.site], capture_output=True, text=True)
        assert build.returncode == 0, build.stdout + build.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_skill(self, *args: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            skill.main(["--site", str(self.site), *args])
        return out.getvalue()

    def test_search(self):
        out = self.run_skill("search", "pot", "helm")
        self.assertIn("Pot Helm | Helmet | Helmets | Meadows | https://mimir.slackworks.com/items/Helmet.html", out)
        self.assertIn("| HelmetFem |", out)
        self.assertIn("| Gem |", self.run_skill("search", "gem"))  # Swamp
        self.assertEqual(self.run_skill("--up-to", "Meadows", "search", "gem"), "no matches\n")
        self.assertIn("| Gem |", self.run_skill("--up-to", "swamp", "search", "gem"))

    def test_show(self):
        out = self.run_skill("show", "pot helm")  # a page name resolves to its id
        self.assertTrue(out.startswith("# Pot Helm (Helmet): items, Meadows\nhttps://mimir.slackworks.com/items/Helmet.html\n{"))
        self.assertIn('"armor": 4', out)
        with self.assertRaises(SystemExit) as e:
            self.run_skill("show", "Helme")
        self.assertIn("did you mean: Pot Helm (Helmet)", str(e.exception))

    def test_get(self):
        out = self.run_skill("get", "Ingot")
        self.assertIn("- smelter at Kiln from Rustore (Ore), fuel Twig (Wood), 30 s", out)
        self.assertIn('earliest way (via): {"how": "process", "from": "Kiln"', out)
        self.assertIn("- spawn (summon): Rod", self.run_skill("get", "Imp"))  # creatures: their spawns

    def test_used_in(self):
        self.assertIn("- smelter input: Ingot at Kiln", self.run_skill("used-in", "Ore"))

    def test_tree(self):
        lines = self.run_skill("tree", "Helmet").splitlines()
        self.assertEqual(lines[0], "Pot Helm (Helmet) · Meadows · craft Recipe_Helmet")
        self.assertIn("  - 2× Ingot · Meadows · process Kiln", lines)
        self.assertIn("    - Rustore (Ore) · Meadows · source Stub", lines)
        self.assertIn("  - Bench · Meadows · build (see above)", lines)  # each subtree once

    def test_list(self):
        out = self.run_skill("list", "items", "--type", "helmet")
        self.assertTrue(out.endswith("3 entries\n"), out)
        self.assertNotIn("FW_Helmet", out)  # enemy-only gear
        self.assertIn("Marble", self.run_skill("list", "items"))  # Mountain
        self.assertNotIn("Marble", self.run_skill("--up-to", "Swamp", "list", "items"))

    def test_fetch_caches(self):  # the live site: fetched once, then read from the cache
        site = self.site

        def urlopen(req, timeout):
            path = req.full_url.removeprefix("https://example.test/")
            return contextlib.closing(io.BytesIO((site / path).read_bytes()))

        with tempfile.TemporaryDirectory() as cache, mock.patch.object(skill.tempfile, "gettempdir", lambda: cache), \
                mock.patch.object(skill.urllib.request, "urlopen", side_effect=urlopen) as fetch:
            self.assertEqual(skill.Data("https://example.test").data("items"), skill.Data(str(site)).data("items"))
            skill.Data("https://example.test").data("items")
            self.assertEqual(fetch.call_count, 1)

    def test_zip(self):  # published by build-site.py, linked from llms.txt
        with zipfile.ZipFile(self.site / "mimir-skill.zip") as z:
            self.assertEqual(sorted(z.namelist()), ["mimir/SKILL.md", "mimir/scripts/mimir.py"])
            md = z.read("mimir/SKILL.md").decode()
            self.assertTrue(md.startswith("---\nname: mimir\ndescription: "))
            self.assertEqual(z.read("mimir/scripts/mimir.py"), (SKILL / "scripts/mimir.py").read_bytes())
        self.assertIn("(https://mimir.slackworks.com/mimir-skill.zip)", (self.site / "llms.txt").read_text())


if __name__ == "__main__":
    unittest.main()

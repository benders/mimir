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

    def test_world_pieces(self):
        chest = (self.out / "pieces/LootChest.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Contains</h2>", chest)
        self.assertRegex(chest, r'href="items/Gem.html".*?</td><td>1–2</td><td>75%</td>')  # weight 3 of 4
        self.assertRegex(chest, r'<h2>Breaks into</h2>.*href="items/Marble.html".*×2')  # 7 // 3; Wood isn't recovered
        self.assertNotIn("<h2>Cost</h2>", chest)
        marble = (self.out / "items/Marble.html").read_text(encoding="utf-8")
        self.assertIn("2, when broken", marble)
        self.assertNotIn("LootChest", (self.out / "items/Wood.html").read_text(encoding="utf-8"))  # not "Used in"
        index = (self.out / "pieces/index.html").read_text(encoding="utf-8")
        world = index[index.index('<h2 id="world"'):]
        self.assertIn("pieces/LootChest.html", world)
        self.assertNotIn("pieces/piece_bench.html", world)  # a plain copy of the Bench: linked from the Bench instead
        self.assertNotIn("pieces/LootChest.html", index[:index.index('<h2 id="world"')])
        tags = re.findall(r'<h2 id="([a-z-]+)"[^>]*>([^<]+)</h2>', index)
        self.assertLess(tags.index(("crafting", "Crafting")), tags.index(("furniture", "Furniture")))  # menu order
        for tag in ("crafting", "furniture"):  # the Bench under each of its tags
            part = index[index.index(f'<h2 id="{tag}"'):]
            self.assertIn("pieces/Bench.html", part[:part.index("</ul>")])
        self.assertIn("Crafting · Furniture", bench_page := (self.out / "pieces/Bench.html").read_text(encoding="utf-8"))
        bench = (self.out / "pieces/Bench.html").read_text(encoding="utf-8")
        self.assertRegex(bench, r'<h2>Also in the world</h2>.*href="pieces/piece_bench.html"')

    def test_sold_by(self):
        charm = (self.out / "items/Charm.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Sold by</h2>", charm)
        self.assertIn("Old Vendor", charm)
        self.assertIn('href="items/Coins.html"', charm)  # the price
        self.assertIn("×50", charm)
        self.assertIn("for ×2", charm)  # stack size
        self.assertIn("<th>After</th><", charm)
        self.assertIn("<td><code>defeated_chief</code></td>", charm)  # no boss sets this key: shown as is
        self.assertIn('Market (<a href="biomes/Meadows.html">Meadows</a>)', charm)

    def test_fishing(self):
        fish = (self.out / "items/Fish.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Fishing</h2>", fish)
        self.assertIn("Caught with", fish)
        self.assertIn('href="items/Wood.html"', fish)  # the bait
        self.assertIn('in <a href="biomes/Ocean.html">Ocean</a>', fish)
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

    def test_spirit(self):
        # most fixture creatures are immune to spirit: DPS leaves it out, and creatures always show their spirit tag
        mace = (self.out / "items/Mace.html").read_text(encoding="utf-8")
        self.assertIn("<dt>DPS*</dt><dd>31.7</dd>", mace)  # (10 + 2 hits x 10 x 2) / 1.575 s, spirit 5 left out
        self.assertIn("* DPS leaves out spirit damage: 10 of 11 creatures are immune to it.", mace)
        self.assertIn("<span>spirit</span>Normal", (self.out / "creatures/Shade.html").read_text(encoding="utf-8"))
        self.assertNotIn("*", (self.out / "items/Sword.html").read_text(encoding="utf-8").split("<h2>Stats")[1][:400])

    def test_creatures_by_biome(self):
        index = (self.out / "creatures/index.html").read_text(encoding="utf-8")
        heads = re.findall(r'<h2 id="(\w+)">', index)
        self.assertEqual(heads, ["Meadows", "Mountain", "Other"])  # progression order; empty biomes left out
        mountain = index[index.index('id="Mountain"'):]
        self.assertLess(mountain.index("Chief"), mountain.index("Pup"))  # bosses first
        # Raider: world spawns in Meadows/Black Forest tie with a location in Swamp/Plains; earliest wins
        self.assertIn("creatures/Raider.html", index[:index.index('id="Mountain"')])
        pup = (self.out / "creatures/Pup.html").read_text(encoding="utf-8")
        self.assertRegex(pup, r"<dt>Biome</dt><dd><a href=\"biomes/Swamp.html\">Swamp</a>, <a href=\"biomes/Mountain.html\">Mountain</a>, <a href=\"biomes/Plains.html\">Plains</a></dd>")  # dungeon outweighs the camp
        self.assertRegex(pup, r"<dt>Faction</dt><dd><a href=\"factions/ForestMonsters.html\">Forest monsters</a></dd>")

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
        self.assertIn("<td>Bite</td><td>12 pierce</td>", ranged)  # chop left out: players are immune (#46)
        self.assertIn("chop and pickaxe are left out", ranged)
        self.assertIn("<h1>Pot Helm (female)</h1>", (self.out / "items/HelmetFem.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Pot Helm</h1>", (self.out / "items/Helmet.html").read_text(encoding="utf-8"))
        names = [e[0] for e in json.loads((self.out / "search.json").read_text(encoding="utf-8"))]
        self.assertEqual(names.count("Raider"), 1)
        self.assertIn("Raider (archer)", names)
        self.assertIn("<h1>Bench</h1>", (self.out / "pieces/Bench.html").read_text(encoding="utf-8"))  # buildable
        self.assertIn("<h1>Bench (world)</h1>", (self.out / "pieces/piece_bench.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Chief</h1>", (self.out / "creatures/Chief.html").read_text(encoding="utf-8"))

    def test_food_comfort_skills_pages(self):
        skills = (self.out / "mechanics/skills.html").read_text(encoding="utf-8")
        self.assertIn("<td>Blades</td><td>1</td>", skills)  # name from $skill_swords, gain step from the Player prefab
        self.assertIn("<td>Run</td><td>0.2</td>", skills)    # no translation: the skill id
        self.assertIn("<td>1</td><td>90</td><td>45</td>", skills)  # death penalty 0.1
        comfort = (self.out / "mechanics/comfort.html").read_text(encoding="utf-8")
        self.assertNotIn("pieces/piece_bench", comfort)  # comfort 2 but not buildable: no world copies

    def test_mechanics_section(self):
        for page in ("index", "blocking", "drops", "creature-levels", "damage-types", "item-upgrades", "adrenaline",
                     "food", "comfort", "skills"):
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

    def test_attack_speed(self):
        sword = (self.out / "items/Sword.html").read_text(encoding="utf-8")
        self.assertIn("<th>DPS</th>", sword)
        # (35 + 2 hits x 35 x 2) / 1.575 s at quality 1; slash +6 per level -> (48 + 5) x 5 / 1.575 at quality 4
        self.assertIn("<tr><td>1</td><td>30</td><td>5</td><td>111.1</td>", sword)
        self.assertIn("<tr><td>4</td><td>48</td><td>5</td><td>168.3</td>", sword)
        self.assertIn("2-attack combo in 1.57 s (3 hits)", sword)
        self.assertIn('href="mechanics/weapons.html"', sword)
        page = (self.out / "mechanics/weapons.html").read_text(encoding="utf-8")
        # grouped by category with the skill in the heading; no secondary attacks in the group: no secondary columns
        self.assertIn('<h3 id="swords">Swords <span class="skill"><a href="mechanics/skills.html">Swords skill</a>', page)
        self.assertIn("<td>3</td><td>1.57</td><td>175</td><td><b>111.1</b></td></tr>", page)  # quality 1
        bow = (self.out / "items/Longbow.html").read_text(encoding="utf-8")
        # 2.5 s full draw at skill 0; 0.5 s at 100, but the 1 s release animation is longer
        self.assertIn("full draw 2.5 s (0.5 s at skill 100), 2.5 s per shot (1 s at skill 100)", bow)
        self.assertNotIn("DPS", bow)  # depends on the ammo
        # Arbal: 1 s fire + 4 s reload (2 at skill 100) + 1 s reload done
        self.assertIn("<td>reload</td><td>4</td><td>6</td><td>4</td>", page)

    def test_biome_pages(self):
        swamp = (self.out / "biomes/Swamp.html").read_text(encoding="utf-8")
        self.assertIn('href="mechanics/raids.html#army_test"', swamp)  # a raid that can come here
        self.assertIn('href="creatures/Raider.html"', swamp)
        raider = (self.out / "creatures/Raider.html").read_text(encoding="utf-8")
        self.assertIn('<a href="biomes/Meadows.html">Meadows</a>', raider)  # biome links on the creature page
        self.assertIn('href="factions/ForestMonsters.html"', raider)
        self.assertIn('href="biomes/index.html"', raider)  # nav

    def test_faction_pages(self):
        f = (self.out / "factions/ForestMonsters.html").read_text(encoding="utf-8")
        self.assertIn("Forest monsters", f)
        self.assertIn('href="creatures/Raider.html"', f)
        self.assertIn("<dt>Attacks</dt><dd>Players</dd>", f)  # the only other faction shown: no page, plain text
        self.assertIn("table class=\"matrix\"", (self.out / "factions/index.html").read_text(encoding="utf-8"))

    def test_mechanics_tables_follow_stage_filter(self):
        page = (self.out / "mechanics/damage-types.html").read_text(encoding="utf-8")
        # a row takes the stage of the entity in its first cell (Chief: Mountain)
        self.assertIn('<tr data-stage="3"><td><a class="ref" href="creatures/Chief.html"', page)
        self.assertNotIn('<tr data-stage="3"><td><a class="ref" href="creatures/Raider.html"', page)

    def test_trader_pages(self):
        t = (self.out / "traders/Vendor.html").read_text(encoding="utf-8")
        self.assertIn("<h1>Old Vendor</h1>", t)
        self.assertIn("1000–4000 m from the world centre", t)
        self.assertIn("removes the rest: one per world", t)  # unique
        self.assertIn('href="items/Charm.html"', t)  # what it sells
        charm = (self.out / "items/Charm.html").read_text(encoding="utf-8")
        self.assertIn('<a href="traders/Vendor.html">Old Vendor</a>', charm)  # Sold by links the trader
        self.assertIn('href="traders/Vendor.html"', (self.out / "biomes/Meadows.html").read_text(encoding="utf-8"))

    def test_raids_page(self):
        page = (self.out / "mechanics/raids.html").read_text(encoding="utf-8")
        self.assertIn('<h3 id="army_test">Something stirs', page)
        self.assertIn("<dt>Until</dt><dd><code>defeated_chief</code>", page)  # no creature sets it in the fixture
        self.assertIn("not for a player who has <code>GP_Chief</code> (nothing sets it) or has found", page)
        self.assertIn('href="pieces/Bench.html"', page)  # a base piece
        self.assertIn("<dt>Roll every</dt><dd>30 min</dd>", page)
        self.assertIn("300 min", page)  # expected wait: 30 / 10%

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
        self.assertTrue(all(len(e) == 6 for e in index))
        stage = {e[1]: e[5] for e in index}
        self.assertEqual((stage["Gem"], stage["Wood"]), (2, 0))  # Swamp, Meadows

    def test_requirements_tree(self):
        sword = (self.out / "items/Sword.html").read_text(encoding="utf-8")
        tree = re.search(r'<h2>Requirements</h2><ul class="tree">(.*?)</ul><p class="note">', sword, re.S).group(1)
        self.assertRegex(tree, r'^<li><details open><summary><b>Test Sword</b> <span class=how>crafted</span></summary>')
        self.assertNotIn('href="items/Sword.html"', tree)  # the root is this page: not a link
        self.assertRegex(tree, r'href="pieces/Bench.html">.*?<span class=role>station</span>')
        self.assertRegex(tree, r'href="pieces/Anvil.html">.*?<span class=role>station upgrade</span>')  # level 2
        self.assertRegex(tree, r'href="items/Ingot.html">.*?<span class="qty">×4</span>.*?<span class=how>smelting</span>')
        self.assertRegex(tree, r'href="pieces/Bench.html">[^\n]*?</a> <span class=role>station</span> <span class=how>see ')
        wood = re.findall(r'href="items/Wood.html">.*?</a> <span class=how>(\w+)', tree)
        self.assertEqual(wood.count("see"), len(wood) - 1)  # expanded once, where it's shallowest
        page = (self.out / "items/Wood.html").read_text(encoding="utf-8")
        req = re.search(r'<h2>Requirements</h2>(.*?)</section>', page, re.S).group(1)
        self.assertTrue(req.startswith("<p>Get it from: "))  # needs nothing: one line, no self-link
        self.assertNotIn('class="tree"', req)

    def test_stage_filter(self):
        gem = (self.out / "items/Gem.html").read_text(encoding="utf-8")
        self.assertIn('<p class="spoiler" data-stage="2">', gem)  # shown only when the filter is below Swamp
        self.assertRegex(gem, r'<a class="stage"[^>]*>Swamp</a>')
        wood = (self.out / "items/Wood.html").read_text(encoding="utf-8")
        self.assertRegex(wood, r'<a class="stage"[^>]*>Meadows</a>')
        self.assertNotIn('class="spoiler"', wood)
        self.assertIn('<select id="stage">', wood)
        self.assertRegex(wood, r'<option value="6">Ashlands</option><option value="">Deep North</option></select>')
        self.assertIn('localStorage.getItem("mimir-stage")', wood)
        index = (self.out / "items/index.html").read_text(encoding="utf-8")
        self.assertIn('<li data-stage="2"><a class="ref" href="items/Gem.html"', index)
        self.assertIn('<li><a class="ref" href="items/Wood.html"', index)
        css = (self.out / "style.css").read_text(encoding="utf-8")
        self.assertIn('html[data-max="0"] [data-stage="2"]', css)
        self.assertIn('html[data-max="1"] p.spoiler[data-stage="2"]', css)
        self.assertNotIn('html[data-max="2"] [data-stage="2"]', css)  # its own stage stays visible
        effects = (self.out / "effects/index.html").read_text(encoding="utf-8")
        self.assertIn('<li data-stage="3"><a class="ref" href="effects/SE_Ward.html"', effects)  # Shard's guardian power
        groups = dict(re.findall(r'<h2 id="(\w+)".*?</h2><ul class="grid">(.*?)</ul>', effects))
        self.assertIn("SE_Ward.html", groups["power"])
        self.assertIn("SE_Stun.html", groups["creature"])  # Raider's bite
        self.assertIn("SE_Wet.html", groups["status"])  # nothing gives it
        self.assertLess(effects.index('id="power"'), effects.index('id="status"'))
        ward = (self.out / "effects/SE_Ward.html").read_text(encoding="utf-8")
        self.assertRegex(ward, r'href="items/Shard.html".*offered at its boss stone')
        self.assertIn('<dt>Group</dt><dd><a href="effects/index.html#power">Forsaken powers</a>', ward)
        self.assertIn("offered at its boss stone", ward)
        stun = (self.out / "effects/SE_Stun.html").read_text(encoding="utf-8")
        self.assertRegex(stun, r'href="creatures/Raider.html".*attack')  # through its internal attack item
        page = (self.out / "mechanics/progression.html").read_text(encoding="utf-8")
        self.assertRegex(page, r"<td>Mountain</td><td>\d+</td>")


if __name__ == "__main__":
    unittest.main()

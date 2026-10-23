"""Tests for scripts/well.py (#79): node selection, graph rules and layout on small invented graphs, checks on the
committed data/, and the home page's markup and site/well.js (it parses; the hover rule)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("well", ROOT / "scripts/well.py")
WELL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WELL)


def via(how="craft", *needs, frm=None):
    """A `via` from needs written "item:Wood", "piece:bench", "creature:Boss"."""
    return {"how": how, "from": frm, "needs": [{n.split(":")[0]: n.split(":")[1]} for n in needs]}


def item(id_, type_="Material", stage="Meadows", how="craft", *needs, **kw):
    return {"id": id_, "name": kw.pop("name", id_), "type": type_, "stage": stage, "via": via(how, *needs), **kw}


def piece(id_, stage="Meadows", *needs, **kw):
    return {"id": id_, "name": id_, "stage": stage, "via": via("build", *needs), **kw}


def world(**extra):
    """A small world: every rule of graph() has something to act on."""
    items = [
        item("Wood", how="source"), item("Ore", how="source"),
        item("Club", "OneHandedWeapon", "Meadows", "craft", "item:Wood", "piece:bench", skill="Clubs", damages={"blunt": 10}),
        item("Berry", "Consumable", how="source"),  # needed by armour: kept
        item("BerryVest", "Chest", "Meadows", "craft", "item:Berry", "piece:bench", armor=8),
        item("Pie", "Consumable", "Meadows", "craft", "item:Spice", "piece:cauldron"),  # food: out
        item("Spice", how="trader"),  # only goes into food: out
        item("FireworksRocket_Red", "Material", "Meadows", "craft", "item:Wood", "piece:bench"),  # out
        item("Perch", "Material", how="fish"), item("Bait", "Ammo", "Meadows", "craft", "item:Wood"),  # fishing: out
        item("questbox", "Misc", how="drop"),  # a trader takes it: out
        item("Cap", "Helmet", "Meadows", "craft", "item:Wood", "piece:bench", armor=1),  # cosmetic: out
        item("ArmorRagsChest", "Chest", "Meadows", "craft", "item:Wood", armor=1),  # the starting rags: in
        item("Nails", "Material", "Meadows", "craft", "item:Ore", "piece:bench"),  # only a ship needs them: in
        item("TrophyDeer", "Trophy", how="drop"),  # the boss's offering: in
        item("Antler", "Material", "BlackForest", "drop", "creature:Boss"),
        item("Pick", "Tool", "BlackForest", "craft", "item:Antler", "piece:bench", skill="Pickaxes"),
        item("Cast", "Material", "BlackForest", "craft", "item:Ore", "piece:bench"),  # folds into the sword
        item("Sword", "OneHandedWeapon", "BlackForest", "process", "item:Cast", "piece:foundry", skill="Swords",
             damages={"slash": 30}),
        item("Key", "Misc", "BlackForest", "drop", "creature:Boss"),  # opens a door: an end
        item("SaddleBoar", "Misc", "Meadows", "craft", "item:Wood", "piece:bench"),  # an end
        item("Seeds", how="source"), item("Turnip", "Material", "Meadows", "source", "piece:sapling"),  # dead ends
        item("Amber", how="source"),  # needs nothing, nothing needs it
        item("Ghost", "Material", unobtainable=True),
    ]
    pieces = [piece("bench", "Meadows", "item:Wood"), piece("cauldron", "Meadows", "item:Wood"),
              piece("foundry", "BlackForest", "item:Ore"), piece("sapling", "Meadows", "item:Seeds"),
              piece("Boat", "Meadows", "item:Wood", "item:Nails", tags=["Transportation"])]
    creatures = [{"id": "Boss", "name": "Boss", "boss": True, "stage": "Meadows",
                  "via": via("spawn", "item:TrophyDeer"), "drops": [{"item": "TrophyDeer"}]}]
    sources = [{"id": "Perch", "kind": "fishing", "baits": [{"item": "Bait"}]},
               {"id": "Trader", "kind": "trader", "takes": [{"item": "questbox", "setsKey": "Q1"}]}]
    data = {"items": items, "pieces": pieces, "creatures": creatures, "sources": sources,
            "locations": [{"id": "Crypt", "biomes": ["Swamp"], "key": "Key"}]}
    for k, v in extra.items():
        data[k] = data[k] + v
    return data


class Selection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = WELL.graph(world())
        cls.ids = {x[1] for x in cls.g.sel}

    def test_left_out(self):
        for gone in ("Pie", "Spice", "FireworksRocket_Red", "Perch", "Bait", "questbox", "Cap", "cauldron", "Ghost"):
            self.assertNotIn(gone, self.ids)

    def test_kept(self):
        for kept in ("Wood", "bench", "Club", "BerryVest", "ArmorRagsChest", "Boss", "Pick", "Sword", "Key",
                     "SaddleBoar"):
            self.assertIn(kept, self.ids)

    def test_needed_comes_back(self):
        self.assertIn("Berry", self.ids)  # a consumable armour needs
        self.assertIn("TrophyDeer", self.ids)  # the boss's offering

    def test_ships_with_their_needs(self):
        self.assertIn("Boat", self.ids)
        self.assertEqual({p[1] for p in self.g.par[("piece", "Boat")]}, {"Wood", "Nails"})
        self.assertIn("Nails", self.ids)  # only the boat needs them

    def test_cast_folds_into_its_product(self):
        self.assertNotIn("Cast", self.ids)
        self.assertEqual({p[1] for p in self.g.par[("item", "Sword")]}, {"Ore", "bench", "foundry"})

    def test_dead_ends_go_in_turn(self):
        for gone in ("Turnip", "sapling", "Seeds"):  # Turnip needed the sapling, the sapling the seeds
            self.assertNotIn(gone, self.ids)

    def test_unconnected_dropped(self):
        self.assertNotIn("Amber", self.ids)

    def test_edges_stay_inside(self):
        for x, ps in self.g.par.items():
            self.assertIn(x, self.g.sel)
            self.assertLessEqual(ps, self.g.sel)

    def test_top_gear(self):
        self.assertIn(("item", "Sword"), self.g.gear)
        self.assertIn(("item", "BerryVest"), self.g.gear)


def chain_world(roots=4, crowd=0):
    """One stage: Hub -> A -> B -> C (ranks 0..3), `roots` items only C needs, `crowd` items needing Hub, a boss."""
    items = [item("Hub", how="source"), item("A", "Material", "Meadows", "craft", "item:Hub"),
             item("B", "Material", "Meadows", "craft", "item:A"),
             item("C", "OneHandedWeapon", "Meadows", "craft", "item:B", *[f"item:R{i}" for i in range(roots)])]
    items += [item(f"R{i}", how="source") for i in range(roots)]
    items += [item(f"K{i}", "Bow", "Meadows", "craft", "item:Hub") for i in range(crowd)]
    items += [item("Late", "OneHandedWeapon", "BlackForest", "craft", "item:Hub")]
    creatures = [{"id": "Boss", "name": "Boss", "boss": True, "stage": "Meadows", "via": via("spawn", "item:C")}]
    return {"items": items, "pieces": [], "creatures": creatures, "sources": [], "locations": []}


class Layout(unittest.TestCase):
    def test_roots_spread_above_their_user(self):
        g = WELL.graph(chain_world(roots=4))
        lay = WELL.layout(g)
        ranks = [lay.rank[("item", f"R{i}")] for i in range(4)]
        self.assertTrue(all(r < lay.rank[("item", "C")] for r in ranks))  # above their first user
        self.assertGreater(len(set(ranks)), 1)  # not piled into one ring

    def test_boss_last_in_its_stage(self):
        g = WELL.graph(chain_world())
        lay = WELL.layout(g)
        meadows = [x for x in g.sel if g.stage(x) == 0]
        self.assertEqual(max(meadows, key=lambda x: lay.ypos[x]), ("creature", "Boss"))

    def test_crowded_ring_splits_in_two_rows(self):
        g = WELL.graph(chain_world(crowd=25))
        lay = WELL.layout(g)
        ring = [("item", f"K{i}") for i in range(25)]
        self.assertEqual(len({lay.ypos[x] for x in ring}), 2)
        self.assertAlmostEqual(lay.slot[ring[0]], 2 * 6.283185307179586 / 26, places=6)  # 25 + A share the ring

    def test_stage_height_follows_its_rings(self):
        lay = WELL.layout(WELL.graph(chain_world()))
        tops = [top for _, top, _, _ in lay.bands] + [lay.H - WELL.TILT - 24]
        heights = [b - a for a, b in zip(tops, tops[1:])]
        self.assertGreater(heights[0], heights[1])  # Meadows' five rings, Black Forest's one
        self.assertEqual(heights[2], WELL.BANDPAD)  # an empty stage keeps only its padding

    def test_rings_are_splayed(self):  # consecutive rings turn by different shares of a slot
        g = WELL.graph(chain_world(roots=0))
        lay = WELL.layout(g)
        self.assertEqual(len({round(lay.theta[("item", x)], 6) for x in ("Hub", "A", "B", "C")}), 4)

    def test_same_input_same_output(self):
        a, b = (WELL.layout(WELL.graph(world())) for _ in range(2))
        self.assertEqual(a.theta, b.theta)
        self.assertEqual(a.ypos, b.ypos)

    def test_same_output_whatever_the_hash_seed(self):  # set order must never decide a tie
        code = ("import importlib.util, json, sys; spec = importlib.util.spec_from_file_location('w', sys.argv[1]); "
                "w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w); "
                "g = w.graph(json.loads(sys.argv[2])); print(w.markup(g, w.layout(g), set()))")
        outs = [subprocess.run([sys.executable, "-c", code, ROOT / "scripts/well.py", json.dumps(world())],
                               check=True, capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": seed}).stdout
                for seed in ("1", "2")]
        self.assertEqual(outs[0], outs[1])


class Icons(unittest.TestCase):  # the home page's "Up to" picker shows the boss closing each stage (#78)
    def setUp(self):
        data = world(items=[item("Jewel", icon="jewel"), item("Gem", icon="gem")], creatures=[
            {"id": "King", "name": "King", "boss": True, "stage": "BlackForest", "via": via("spawn", "item:Wood")},
            {"id": "King_p2", "name": "King", "boss": True, "stage": "BlackForest", "via": via("phase", frm="King"),
             "drops": [{"item": "Gem"}, {"item": "Jewel"}]}])
        data["items"] = [dict(i, icon="deer") if i["id"] == "TrophyDeer" else i for i in data["items"]]
        self.g = WELL.graph(data)

    def test_trophy(self):
        self.assertEqual(WELL.icon(self.g, ("creature", "Boss")), "deer")
        self.assertEqual(WELL.icon(self.g, ("item", "Jewel")), "jewel")

    def test_no_trophy_last_phase_last_drop(self):
        self.assertEqual(WELL.icon(self.g, ("creature", "King")), "jewel")

    def test_stage_bosses(self):  # a later phase isn't a boss of its own
        self.assertEqual(WELL.stage_bosses(self.g), {0: ("creature", "Boss"), 1: ("creature", "King")})


class RealData(unittest.TestCase):
    """The committed data/: known content in, known exclusions out."""
    @classmethod
    def setUpClass(cls):
        cls.g = WELL.graph(WELL.load(ROOT / "data"))
        cls.lay = WELL.layout(cls.g)
        cls.ids = {x[1] for x in cls.g.sel}

    def test_known_nodes(self):
        for x in ("Wood", "Hammer", "piece_workbench", "Karve", "Cart", "BronzeNails", "IronScrap", "SilverOre",
                  "Eikthyr", "gd_king", "Bonemass", "Dragon", "GoblinKing", "SeekerQueen", "Fader"):
            self.assertIn(x, self.ids)

    def test_every_boss(self):
        self.assertLessEqual(self.g.bosses, self.g.sel)
        self.assertGreaterEqual(len(self.g.bosses), 8)

    def test_known_exclusions(self):
        for x in ("Fish1", "FishingBait", "ArmorTunic1", "chest_hildir1", "FireworksRocket_Red", "SpiceForests",
                  "Turnip", "TrophyEikthyr", "CookedMeat"):
            self.assertNotIn(x, self.ids)

    def test_known_links(self):
        par = lambda i: {p[1] for p in self.g.par[("item", i)]}
        self.assertIn("CryptKey", par("IronScrap"))  # behind the Sunken Crypt's door
        self.assertIn("Wishbone", par("SilverOre"))  # found with it
        self.assertIn("Gold", par("THSwordGold"))  # the cast folded in

    def test_stage_bosses(self):
        b = WELL.stage_bosses(self.g)
        self.assertEqual(sorted(b), list(range(8)))  # every biome closes with a boss; Post-game has none
        self.assertEqual(WELL.icon(self.g, b[0]), "TrophyEikthyr")
        self.assertEqual(WELL.icon(self.g, b[7]), "crownjewel")  # the Frozen King has no trophy

    def test_size(self):
        self.assertTrue(400 <= len(self.g.sel) <= 800, len(self.g.sel))
        self.assertTrue(all(len(r) <= 40 for r in self.lay.rings), max(map(len, self.lay.rings)))


class Markup(unittest.TestCase):
    """The well's markup on the home page, from data/ without icons, and site/well.js."""
    @classmethod
    def setUpClass(cls):
        cls.g = WELL.graph(WELL.load(ROOT / "data"))
        cls.html = WELL.markup(cls.g, WELL.layout(cls.g), set(), {"Meadows": "biomes/Meadows.html"})
        cls.script = (ROOT / "site/well.js").read_text()

    def test_every_node_once(self):
        self.assertEqual(len(re.findall(r'<a href="[^"]+" class="node', self.html)), len(self.g.sel))

    def test_data(self):
        blob = re.search(r'<script type="application/json" id="well-data">(.*?)</script>', self.html, re.S).group(1)
        data = json.loads(blob)
        self.assertEqual(len(data["a"]), len(self.g.sel))
        self.assertEqual(sum(map(len, data["par"])), sum(map(len, self.g.par.values())))

    def test_band_links(self):
        self.assertIn('<a href="biomes/Meadows.html">Meadows</a>', self.html)
        self.assertNotIn('href="biomes/Swamp.html"', self.html)  # no link given

    def test_size_budget(self):
        self.assertLess(len(self.html.encode()), 250_000)  # 170 KB now; #76 will set the real budget

    def node(self, js: str) -> str:
        if not shutil.which("node"):
            self.skipTest("node isn't installed")
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()

    def test_script_parses(self):  # a stray // once commented out the edge drawing
        self.node(f"new Function({json.dumps(self.script)}); console.log('ok')")

    def test_hover_lights_paths_through_the_node(self):
        walk = re.search(r"function walk\(.*?return s\}", self.script).group(0)
        hot = re.search(r"const hot=(.*?);", self.script).group(1)
        # 0 -> 1 -> 2, and 0 -> 3: hovering 1, the edge 0 -> 3 skips it
        js = (f"{walk}; const D={{par:[[],[0],[1],[0]],c:[0,0,0,0]}}, KID=[[1,3],[2],[],[]], on=true, MAX=99;"
              f"const up=walk(1,D.par,new Set([1])), down=walk(1,KID,new Set([1]));"
              f"const lit=(p,c)=>!!({hot}); console.log([lit(0,1),lit(1,2),lit(0,3)].join())")
        self.assertEqual(self.node(js), "true,true,false")

    def test_trace_stops_at_the_stage(self):  # #77: hovering can't trace into what "Up to" hides
        walk = re.search(r"function walk\(.*?return s\}", self.script).group(0)
        js = (f"{walk}; const D={{c:[0,1,2]}}, KID=[[1],[2],[]], MAX=1;"
              f"console.log([...walk(0,KID,new Set([0]))].join())")
        self.assertEqual(self.node(js), "0,1")

    def test_hidden_nodes_carry_their_stage(self):  # #77: the site's stage CSS hides them with no script
        data = json.loads(re.search(r'id="well-data">(.*?)</script>', self.html, re.S).group(1))
        for n, st in re.findall(r'class="node[^"]*" data-n="(\d+)"(?: data-stage="(\d)")?', self.html):
            self.assertEqual(int(st or 0), data["c"][int(n)], n)
        self.assertEqual(len(re.findall(r'class="node[^"]*" data-n=', self.html)), len(self.g.sel))
        for i in range(1, len(WELL.S)):
            self.assertIn(f'<div class="bandname" data-s="{i}" data-stage="{i}"', self.html)

    def test_cut_at_the_stage(self):  # #77: the well ends at the chosen stage's floor, the deeper bands listed below
        data = json.loads(re.search(r'id="well-data">(.*?)</script>', self.html, re.S).group(1))
        H = int(re.search(r'<div class="well" style="--h:(\d+)px"', self.html).group(1))
        cuts = [int(c) for c in re.findall(r'\.well\{--cut:(\d+)px\}', self.html)]
        self.assertEqual(len(cuts), len(WELL.S) - 1)  # Post-game: no cut
        self.assertEqual(cuts, sorted(cuts))
        self.assertLess(cuts[-1], H)
        for m, cut in enumerate(cuts):  # past every node of the stage, short of the next band's
            self.assertGreater(cut, max(y for y, c in zip(data["y"], data["c"]) if c <= m))
            self.assertLess(cut, min(y for y, c in zip(data["y"], data["c"]) if c > m))
        self.assertIn('html[data-max="2"] .deeper li[data-s="3"]{display:flex}', self.html)
        self.assertNotIn('html[data-max="2"] .deeper li[data-s="2"]', self.html)
        self.assertEqual(len(re.findall(r'<li data-s="\d" style="--tier:[^"]+"><button type="button" data-upto=', self.html)),
                         len(WELL.S) - 1)
        self.assertIn('<button type="button" data-upto="">Post-game</button>', self.html)


if __name__ == "__main__":
    unittest.main()

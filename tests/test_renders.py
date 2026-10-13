"""Unit tests for scripts/extract-renders.py: the rules read from the raw dump (random spawns, lit fires, entrances,
camp rooms), the terrain heightmap and the rasterizer on a synthetic scene. They need numpy, numba, UnityPy and
Pillow (requirements.txt), so `make test` skips them unless those are installed; `make test-renders` runs them in
the extractors' venv. Invented values only."""
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    spec = importlib.util.spec_from_file_location("extract_renders", ROOT / "scripts/extract-renders.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    import numpy as np
except ImportError as e:  # stdlib-only python: the venv has these
    R, MISSING = None, str(e)


def comp(type_, path, **fields):
    return {"type": type_, "path": path, "fields": fields}


@unittest.skipIf(R is None, f"needs the extractors' venv ({'' if R else MISSING})")
class Rules(unittest.TestCase):
    def test_random_spawns(self):
        loc = {"components": [
            comp("RandomSpawn", "house/vines (2)", m_chanceToSpawn=10),            # rare decoration: left out
            comp("RandomSpawn", "house/ivy", m_chanceToSpawn=50),                  # common decoration: kept
            comp("RandomSpawn", "house/roof", m_chanceToSpawn=10,                  # structure: kept at any chance
                 m_OffObject={"path": "house/roof_broken"}),
            comp("RandomSpawn", "house/Pickable_Mushroom", m_chanceToSpawn=20,     # left out: its off object instead
                 m_OffObject={"path": "house/grass"}),
            comp("RandomSpawn", "house/beehive", m_chanceToSpawn=100)]}
        self.assertEqual(R.random_spawns(loc), {"house/vines (2)": False, "house/roof_broken": False,
                                                "house/Pickable_Mushroom": False, "house/grass": True})

    def test_lit_fires(self):
        loc = {"components": [
            comp("Fireplace", "bonfire", m_startFuel=10, m_enabledObject={"path": "bonfire/_enabled"}),
            comp("Fireplace", "torch", m_startFuel=0, m_infiniteFuel=True, m_enabledObject={"path": "torch/_on"}),
            comp("Fireplace", "hearth", m_startFuel=0, m_enabledObject={"path": "hearth/_enabled"})]}  # starts out
        self.assertEqual(R.lit_fires(loc), {"bonfire/_enabled": True, "torch/_on": True})

    def test_entrance_marks(self):
        loc = {"components": [comp("Teleport", "Entrance/portal"), comp("Teleport", "Interior/exit"),
                              comp("Door", "Hut/door")],
               "instances": [{"prefab": "dungeon_gate", "path": "Gate"}, {"prefab": "stone_stair", "path": "Steps"},
                             {"prefab": "wood_ladder", "path": "Interior/ladder"}]}
        self.assertEqual(R.entrance_marks(loc), {"Entrance/portal": 3, "Hut/door": 2, "Gate": 2, "Steps": 1})

    def test_camp_rooms(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "locations").mkdir()
            (raw / "rooms").mkdir()
            (raw / "room_themes.json").write_text(json.dumps({"Crypt": 1, "Village": 2, "Camp": 4}))

            def dump(rel, obj):
                (raw / rel).write_text(json.dumps(obj))
            dump("locations/Village.json", {"components": [
                comp("DungeonGenerator", None, m_algorithm="CampRadial", m_themes="Village, Camp")]})
            dump("locations/Crypt.json", {"components": [comp("DungeonGenerator", None, m_algorithm="Dungeon",
                                                              m_themes="Crypt")]})
            for name, theme, enabled in (("hut", 2, True), ("tent", "Camp", True), ("hall", 1, False),
                                         ("well", 2, False), ("crypt_room", 1, True)):
                dump(f"rooms/{name}.json", {"name": name, "theme": theme, "enabled": enabled, "components": []})
            self.assertEqual(R.camp_rooms(raw), {"hut", "tent"})  # not disabled ones, not underground ones


@unittest.skipIf(R is None, "needs the extractors' venv")
class Drawing(unittest.TestCase):
    def test_terrain(self):
        level = {"m_level": True, "m_levelRadius": 2, "m_levelOffset": 0.5, "m_smooth": True, "m_smoothRadius": 6,
                 "m_smoothPower": 1, "m_sortOrder": 0}
        t = R.Terrain([((0.0, 1.0, 0.0), level)], -10, 10, -10, 10)
        h = t.height(np.array([0.0, 4.0, 6.0, 9.0]), np.zeros(4))
        self.assertAlmostEqual(h[0], 1.5)                  # levelled to the modifier's height + offset
        self.assertAlmostEqual(h[1], 1.5 * (1 - 4 / 6))   # smoothed toward it: t = 1 - (d / r) ^ power
        self.assertAlmostEqual(h[2], 0)                    # flat past the smooth radius
        self.assertEqual(t.height(np.array([50.0]), np.array([0.0]))[0], 0)  # off the grid

    def scene(self, weight=0):
        """A 4 m upright wall at the origin, untextured."""
        s = R.Scene()
        w = np.array([[-2.0, 0, 0], [2, 0, 0], [2, 4, 0], [-2, 4, 0]])
        m = {"name": "wall", "tex": None, "tint": np.ones(3), "st": (1, 1, 0, 0), "cutoff": None, "glass": False,
             "skip": False}
        s.parts.append((w, np.zeros((4, 2)), np.array([[0, 1, 2], [0, 2, 3]]), m, weight))
        return s

    def test_render(self):
        img = R.render(self.scene(), 40)
        self.assertEqual(img.size, (R.SIZE, R.SIZE))
        a = np.asarray(img)[..., 3]
        self.assertEqual(a[0, 0], 0)                # transparent corner (the ground fades out in a circle)
        self.assertEqual(a[R.SIZE // 2, R.SIZE // 2], 255)  # the wall, framed in the middle
        self.assertIsNone(R.render(R.Scene(), 40))  # nothing to draw

    def test_probe(self):
        self.assertEqual(R.render(self.scene(), 40, probe=True), 0)  # no entrance
        seen = R.render(self.scene(weight=2), 40, probe=True)
        self.assertGreater(seen, 0)
        # from behind (180 degrees) the same wall is just as visible
        self.assertAlmostEqual(R.render(self.scene(weight=2), 40, R.YAW + math.pi, probe=True), seen, delta=seen * 0.1)


if __name__ == "__main__":
    unittest.main()

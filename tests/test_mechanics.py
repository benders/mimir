"""Unit tests for scripts/mechanics.py: the Markdown renderer, the formulas (hand-worked from the decompiled code)
and the SVG charts."""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mechanics", ROOT / "scripts/mechanics.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Formulas(unittest.TestCase):
    def test_armor_branches(self):
        # HitData.DamageTypes.ApplyArmor: ac < dmg/2 -> dmg - ac, else clamp01(dmg/(4 ac)) * dmg
        self.assertEqual(M.armor_through(100, 20), 80)
        self.assertEqual(M.armor_through(100, 50), 50)   # the branches meet: 100^2 / 200
        self.assertEqual(M.armor_through(100, 100), 25)  # 100^2 / 400
        self.assertEqual(M.armor_through(60, 120), 7.5)
        self.assertEqual(M.armor_through(100, 0), 100)   # ac <= 0 is a no-op
        self.assertGreater(M.armor_through(100, 10000), 0)

    def test_block_power(self):
        # (42 + 6 * 2) * (1 + 0.5 * 0.5) = 67.5; parry x1.5
        self.assertEqual(M.block_power(42, 6, 3, 50), 67.5)
        self.assertEqual(M.block_power(42, 6, 3, 50, 1.5), 101.25)
        self.assertEqual(M.block_power(6, 6, 1, 0), 6)
        self.assertEqual(M.block_power(10, 0, 1, 250), 15)   # skill clamped to 100
        self.assertAlmostEqual(M.block_power(10, 0, 1, 99.9), 10 * (1 + 0.5 * 0.99))  # floored level

    def test_block_outcome(self):
        o = M.block_outcome(100, 50)  # D == 2B
        self.assertEqual((o["through"], o["blocked"], o["stamina_fraction"]), (50, 50, 1.0))
        o = M.block_outcome(50, 50)   # x = 1: x - x^2/4 = 0.75
        self.assertAlmostEqual(o["stamina_fraction"], 0.75)
        self.assertEqual(M.block_outcome(100, 25)["through"], 75)

    def test_stars(self):
        self.assertEqual(M.star_multipliers(0), {"health": 1, "damage": 1.0, "drops": 1})
        self.assertEqual(M.star_multipliers(2), {"health": 3, "damage": 2.0, "drops": 4})
        self.assertEqual(M.star_multipliers(3)["drops"], 8)

    def test_level_distribution(self):
        d = M.level_distribution(10, 1, 3)
        self.assertAlmostEqual(d[1], 0.9)
        self.assertAlmostEqual(d[2], 0.09)
        self.assertAlmostEqual(d[3], 0.01)
        self.assertEqual(M.level_distribution(10, 2, 2), {2: 1.0})
        self.assertAlmostEqual(sum(M.level_distribution(15, 1, 5).values()), 1)

    def test_upgrade_cost(self):
        self.assertEqual([M.upgrade_cost_multiplier(q) for q in range(1, 7)], [0, 1, 2, 4, 4.5, 5])

    def test_pseudo(self):
        self.assertEqual(M.pseudo_gap_max(0.25), 8)  # Range(0, 9) -> 0..8
        self.assertAlmostEqual(M.pseudo_rate(0.25), 9 / 37)

    def test_should_override(self):
        o = M.should_override
        self.assertFalse(o("Ignore", "Immune"))
        self.assertTrue(o("Normal", "Resistant"))
        self.assertFalse(o("VeryResistant", "Resistant"))
        self.assertTrue(o("Resistant", "VeryResistant"))
        self.assertFalse(o("Resistant", "Weak"))
        self.assertTrue(o("Weak", "Resistant"))
        self.assertTrue(o("Immune", "Resistant"))  # order dependent, as the code is

    def test_modifier_multipliers(self):
        self.assertEqual(M.MODIFIER_MULTIPLIER["VeryWeak"], 2.0)
        self.assertEqual(M.MODIFIER_MULTIPLIER["SlightlyResistant"], 0.75)


class Markdown(unittest.TestCase):
    def r(self, text, **kw):
        return M.render(text, M.Ctx(**kw))

    def test_front_matter(self):
        meta, body = M.parse_front_matter("---\ntitle: A B\norder: 2\n---\nhello\n")
        self.assertEqual(meta, {"title": "A B", "order": "2"})
        self.assertEqual(body, "hello\n")
        self.assertEqual(M.parse_front_matter("no front"), ({}, "no front"))

    def test_blocks(self):
        h = self.r("## Head\n\nA *b* **c** `x<y` $D² / 4$\nsecond line\n\n- one\n- two\n  more\n\n1. a\n2. b\n\n> note\n")
        self.assertIn('<h2 id="head">Head</h2>', h)
        self.assertIn("<p>A <i>b</i> <b>c</b> <code>x&lt;y</code> "
                      '<span class="formula">D² / 4</span> second line</p>', h)
        self.assertIn("<ul><li>one</li><li>two more</li></ul>", h)
        self.assertIn("<ol><li>a</li><li>b</li></ol>", h)
        self.assertIn("<blockquote><p>note</p></blockquote>", h)
        self.assertIn('class="inferred"', self.r("> Inferred: maybe"))

    def test_table_and_code(self):
        h = self.r("| A | B |\n|---|---:|\n| 1 | `x` |\n\n```\n<b>\n```\n")
        self.assertIn('<table class="num"><thead><tr><th>A</th><th>B</th></tr></thead>', h)
        self.assertIn("<td>1</td><td><code>x</code></td>", h)
        self.assertIn("<pre><code>&lt;b&gt;</code></pre>", h)
        self.assertNotIn('class="num"', self.r("| A |\n|---|\n| 1 |"))

    def test_escaping_and_links(self):
        h = self.r("a <script> [t](item:Foo) [u](https://x.y/?a=1&b=2) [m](mechanic:blocking)",
                   resolve=lambda s, i: f"{s}s/{i}.html")
        self.assertIn("&lt;script&gt;", h)
        self.assertIn('<a href="items/Foo.html">t</a>', h)
        self.assertIn('<a href="https://x.y/?a=1&amp;b=2">u</a>', h)
        self.assertIn('href="mechanics/blocking.html"', h)
        with self.assertRaises(ValueError):
            self.r("[t](item:Foo)")

    def test_directives(self):
        self.assertIn("<i>hi</i>", self.r("{{x}}", blocks={"x": lambda: "<i>hi</i>"}))
        self.assertIn("<i>a</i>", self.r("{{chart a}}", blocks={"chart": lambda n: f"<i>{n}</i>"}))
        with self.assertRaises(ValueError):
            self.r("{{nope}}")

    def test_calculator_hook(self):
        ctx = M.Ctx()
        self.assertEqual(M.render("{{calculator absent}}", ctx), "")  # no site/calc/absent.js: renders nothing
        self.assertEqual(ctx.scripts, [])
        tmp = ROOT / ".cache" / "calc-test"
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "demo.js").write_text("//")
        self.assertIn('data-calc="demo"', M.calculator_block("demo", ctx, tmp))
        self.assertEqual(ctx.scripts, ["calc/demo.js"])


class Charts(unittest.TestCase):
    def points(self, svg):
        return [[tuple(map(float, p.split(","))) for p in m.split()] for m in re.findall(r'class="ln s\d" points="([^"]+)"', svg)]

    def test_armor_chart(self):
        svg = M.armor_chart()
        self.assertIn("<svg", svg)
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        self.assertIn('role="img"', svg)
        self.assertEqual(len(self.points(svg)), 3)
        self.assertIn("takes 50% at armor 30, 25% at armor 60 and 12.5% at armor 120", svg)
        self.assertNotIn("<script", svg)

    def test_series_follow_formula(self):
        svg = M.line_chart([{"label": "t", "points": [(0, 0), (1, 1)]}], xlim=(0, 1), ylim=(0, 1), xticks=[0, 1],
                           yticks=[0, 1], xlabel="x", ylabel="y", title="t", desc="d")
        (pts,) = self.points(svg)
        self.assertEqual(len(pts), 2)
        self.assertLess(pts[1][1], pts[0][1])  # y grows upward in value, downward in SVG coordinates

    def test_other_charts(self):
        self.assertIn("A 100 hit leaves 60 against block power 40 and 25 against block power 100", M.block_chart())
        self.assertIn("health ×3, damage ×2, level-multiplied drops ×4", M.stars_chart())


if __name__ == "__main__":
    unittest.main()

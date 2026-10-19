"""Unit tests for scripts/mechanics_sources.py (#60): finding cited methods in ILSpy output, the check/accept record,
and that every mechanics page citation has a recorded hash."""
import importlib.util
import json
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("mechanics_sources", ROOT / "scripts/mechanics_sources.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

# Invented code in ILSpy's layout (tabs, braces on their own lines).
CODE = """using System;

public class Widget : MonoBehaviour
{
\tpublic enum Mode
\t{
\t\tOff,
\t\tOn
\t}

\tpublic class Part
\t{
\t\tpublic float m_size = 1f;

\t\tpublic float GetSize(int level)
\t\t{
\t\t\treturn m_size * (float)level;
\t\t}
\t}

\tprivate float m_value;

\tpublic float Value
\t{
\t\tget
\t\t{
\t\t\treturn m_value;
\t\t}
\t}

\tpublic void Spin(float dt)
\t{
\t\tm_list.RemoveWhere((string x) =>
\t\t{
\t\t\treturn x == "{";
\t\t});
\t\tm_value += dt;
\t}

\tpublic void Spin()
\t{
\t\tSpin(1f);
\t}

\tpublic T Get<T>(string name) where T : class
\t{
\t\treturn null;
\t}

\tpublic bool IsOn() => m_value > 0f;

\tpublic void After()
\t{
\t}
}
"""


def index(code=CODE):
    blocks = defaultdict(list)
    S.index_source(code, blocks)
    return blocks


class Index(unittest.TestCase):
    def test_names(self):
        b = index()
        for name in ("Widget", "Widget.Mode", "Widget.Part", "Widget.Part.GetSize", "Widget.Spin", "Widget.Get",
                     "Widget.IsOn", "Widget.After"):
            self.assertIn(name, b)
        self.assertNotIn("Widget.Value", b)          # properties aren't methods
        self.assertNotIn("Widget.RemoveWhere", b)    # nor calls with lambda bodies
        self.assertEqual(len(b["Widget.Spin"]), 2)   # overloads
        self.assertIn("m_value += dt;", b["Widget.Spin"][0])  # the `});` line doesn't end the method
        self.assertTrue(b["Widget.After"][0].rstrip().endswith("}"))

    def test_namespace(self):
        b = index("namespace Game.Things\n{\n\tpublic class Box\n\t{\n\t\tpublic void Open()\n\t\t{\n\t\t}\n\t}\n}\n")
        self.assertIn("Box.Open", b)

    def test_resolve(self):
        b = index()
        self.assertEqual(S.resolve("Widget.Part.GetSize", b), b["Widget.Part.GetSize"])
        self.assertEqual(S.resolve("Part.GetSize", b), b["Widget.Part.GetSize"])  # unique suffix
        self.assertIsNone(S.resolve("Widget.Missing", b))
        b["Other.Part.GetSize"].append("x")
        self.assertIsNone(S.resolve("Part.GetSize", b))  # ambiguous

    def test_digest(self):
        b = index()
        reindented = index(CODE.replace("\t", "    "))
        self.assertEqual(S.digest(b["Widget.Spin"]), S.digest(reindented["Widget.Spin"]))
        self.assertEqual(S.digest(b["Widget.Spin"]), S.digest(list(reversed(b["Widget.Spin"]))))
        changed = index(CODE.replace("m_value += dt;", "m_value -= dt;"))
        self.assertNotEqual(S.digest(b["Widget.Spin"]), S.digest(changed["Widget.Spin"]))


class Record(unittest.TestCase):
    old = {"a": {"version": "1.0", "methods": {"X.F": "h1", "X.G": "h2"}},
           "b": {"version": "1.0", "methods": {"Y.F": "h3"}}}

    def test_check(self):
        now = {"a": {"X.F": "h1", "X.G": "h2"}, "b": {"Y.F": "new"}, "c": {"Z.F": "h4"}}
        r = S.check(self.old, now, "1.1")
        self.assertEqual(r["a"], {"version": "1.1", "methods": {"X.F": "h1", "X.G": "h2"}})  # unchanged: moves on
        self.assertEqual(r["b"], {"version": "1.0", "methods": {"Y.F": "h3"}, "changed": ["Y.F"], "changedIn": "1.1"})
        self.assertEqual(r["c"]["changed"], ["Z.F"])  # never accepted
        self.assertEqual(r["c"]["version"], "")
        # still stale on the next update: keeps when it first changed
        self.assertEqual(S.check(r, now, "1.2")["b"]["changedIn"], "1.1")
        # a missing method is a change
        self.assertEqual(S.check(self.old, {"a": {"X.F": None, "X.G": "h2"}}, "1.1")["a"]["changed"], ["X.F"])

    def test_accept(self):
        stale = S.check(self.old, {"a": {"X.F": "h1", "X.G": "h2"}, "b": {"Y.F": "new"}}, "1.1")
        r = S.accept(stale, {"a": {"X.F": "h1", "X.G": "h2"}, "b": {"Y.F": "new"}}, "1.1", ["b"])
        self.assertEqual(r["b"], {"version": "1.1", "methods": {"Y.F": "new"}})
        with self.assertRaises(SystemExit):
            S.accept(stale, {"a": {"X.F": None}, "b": {"Y.F": "new"}}, "1.1", ["a"])

    def test_report(self):
        self.assertEqual(S.report(self.old), "")
        r = S.check(self.old, {"a": {"X.F": "h1", "X.G": "h2"}, "b": {"Y.F": "new"}}, "1.1")
        text = S.report(r)
        self.assertIn("**b** (verified 1.0): `Y.F`", text)
        self.assertNotIn("**a**", text)


class Committed(unittest.TestCase):
    def test_every_citation_recorded(self):
        """A new page or citation needs `make mechanics-accept` (against the current decompile)."""
        record = json.loads(S.RECORD.read_text(encoding="utf-8"))
        sources = S.page_sources()
        self.assertEqual(sorted(record), sorted(sources))
        for page, cites in sources.items():
            missing = [c for c in cites if c not in record[page]["methods"]]
            self.assertFalse(missing, f"{page}: no recorded hash for {missing}: run make mechanics-accept PAGES={page}")
            self.assertTrue(record[page]["version"], page)


if __name__ == "__main__":
    unittest.main()

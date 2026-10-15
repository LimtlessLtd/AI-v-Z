"""Tests for the pure helpers in agent/site.py (num, text, dct, label, detail).

They need no numpy, so they run here; site.py only imports it for the network export. When numpy is missing a
stand-in is put in place for the import and removed again, so tests/test_site.py still skips as it should.

Run from the repo root:  python -m unittest discover -s tests
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_stub = importlib.util.find_spec("numpy") is None
if _stub:
    sys.modules["numpy"] = types.ModuleType("numpy")
try:
    from agent import site  # noqa: E402
finally:
    if _stub:
        del sys.modules["numpy"]


class SiteHelpers(unittest.TestCase):
    def test_num_is_finite_and_rounded_else_none(self):
        self.assertEqual(site.num(1.2345), 1.23)
        self.assertEqual(site.num(1.5, 3), 1.5)
        self.assertEqual(site.num(2.6, 0), 3)
        self.assertIsNone(site.num(float("nan")))
        self.assertIsNone(site.num(float("inf")))
        self.assertIsNone(site.num(True))
        self.assertIsNone(site.num("3"))
        self.assertIsNone(site.num(None))

    def test_text_and_dct_fall_back_to_empty(self):
        self.assertEqual(site.text("a"), "a")
        self.assertEqual(site.text(3), "")
        self.assertEqual(site.dct({"a": 1}), {"a": 1})
        self.assertEqual(site.dct([1]), {})

    def test_label_takes_the_first_filled_field(self):
        self.assertEqual(site.label({"name": "Axe", "dir": "N"}), "Axe")
        self.assertEqual(site.label({"name": "", "dir": "N"}), "N")
        self.assertEqual(site.label({"part": "Hand_L", "type": "x"}), "Hand_L")
        self.assertEqual(site.label({"type": 5}), "5")
        self.assertEqual(site.label({}), "")

    def test_detail_names_the_visible_fields(self):
        self.assertEqual(site.detail({}), "")
        self.assertEqual(site.detail({"d": 3, "zombies": 2}), "3 tiles, 2 zombies that way")
        self.assertEqual(site.detail({"verb": "door", "open": False}), "closed")
        self.assertEqual(site.detail({"verb": "door", "open": True, "locked": True}), "open, locked")
        self.assertEqual(site.detail({"open": True}), "")   # only doors, windows and curtains show open/closed
        self.assertEqual(site.detail({"bleeding": "yes"}), "")   # flags count only when exactly true
        self.assertEqual(site.detail({"verb": "barricade", "planks": 2}), "2 planks up")
        self.assertEqual(site.detail({"how": "half", "n": 6}), "half of the pile (6)")
        self.assertEqual(site.detail({"from": "a", "to": "b", "item": "Saw", "minutes": 5, "cost": 1}),
                         "with Saw, from a, to b, 5 min, cost 1")

    def test_detail_facing_uses_the_feature_words(self):
        for value in (0.0, 0.5, 1.0):
            text = site.detail({"facing": value})
            self.assertIn(text, ("facing it", "facing away", "facing side-on"))


class SiteLives(unittest.TestCase):
    def test_pick_lives_recent_longest_and_current(self):
        history = [{"life": n, "hours": n % 7} for n in range(1, 31)] + [{"life": "x"}, {"hours": 9}]
        recent, longest, now = site.pick_lives(history, types.SimpleNamespace(number=31))
        self.assertEqual(recent, list(range(21, 31)))   # the last RECENT finished lives, junk rows skipped
        self.assertEqual(len(longest), 30)               # LONGEST * 4 candidates, but only 30 lives exist
        self.assertEqual(longest[0] % 7, 6)              # longest first
        self.assertEqual(now, [31])
        self.assertEqual(site.pick_lives([], None), ([], [], []))

    def test_collect_parses_only_wanted_lives(self):
        import gzip
        import json
        import tempfile
        rec = lambda n, **kw: json.dumps({"ts": "t", "life": n, "obs": {"traits": ["Lucky", 5]}, **kw})
        lines = [rec(1), rec(2, reason="creation"), rec(2), rec(3), "not json", '{"life": 2, "x": [', rec(2)]
        with tempfile.TemporaryDirectory() as d:
            with gzip.open(Path(d) / "a.jsonl.gz", "wt") as f:
                f.write("\n".join(lines) + "\n")
            steps, traits = site.collect(d, {2, 9})
        self.assertEqual(set(steps), {2, 9})
        self.assertEqual(len(steps[2]), 2)               # creation record and bad JSON skipped
        self.assertEqual(steps[9], [])
        self.assertEqual(traits, {2: ["Lucky", ""]})     # traits as text (non-strings blank), from the first kept record


if __name__ == "__main__":
    unittest.main()

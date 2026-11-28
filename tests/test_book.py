"""The book, Aligned to what? (site/book.json): every chapter placed once, every paragraph sourced,
quotes short, every tradition coded with values that exist, the timeline in order."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = json.loads((ROOT / "site" / "book.json").read_text(encoding="utf-8"))
URL = re.compile(r"^https?://\S+$")
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def quotes(o, out):
    if isinstance(o, dict):
        if "quote" in o:
            out.append(o)
        for v in o.values():
            quotes(v, out)
    elif isinstance(o, list):
        for v in o:
            quotes(v, out)
    return out


class Book(unittest.TestCase):
    def test_every_chapter_is_placed_exactly_once(self):
        ids = [c["id"] for c in BOOK["chapters"]]
        placed = [i for p in BOOK["parts"] for i in p["chapters"]]
        self.assertEqual(sorted(ids), sorted(placed))
        self.assertEqual(len(placed), len(set(placed)))

    def test_every_paragraph_has_a_source(self):
        for c in BOOK["chapters"]:
            self.assertTrue(c["title"] and c["summary"], c["id"])
            for s in c["sections"]:
                for p in s["paragraphs"]:
                    self.assertTrue(p["text"].strip(), c["id"])
                    self.assertTrue(p["sources"], f"{c['id']}: {p['text'][:60]}")
                    for src in p["sources"]:
                        self.assertRegex(src["url"], URL)
                        self.assertTrue(src["title"])

    def test_quotes_are_short_and_linked(self):
        qs = quotes(BOOK, [])
        self.assertGreater(len(qs), 300)
        for q in qs:
            self.assertLessEqual(len(q["quote"].split()), 30, q["quote"][:60])
            self.assertRegex(q["url"], URL)

    def test_traditions_are_coded_with_known_values(self):
        T = BOOK["taxonomy"]
        dims = {d["id"]: {v["id"] for v in d["values"]} for d in T["dimensions"]}
        ids = [t["id"] for t in T["traditions"]]
        self.assertEqual(len(ids), len(set(ids)))
        for t in T["traditions"]:
            self.assertEqual(set(t["codes"]), set(dims), t["id"])
            for d, v in t["codes"].items():
                self.assertIn(v, dims[d], f"{t['id']}.{d}")
            self.assertTrue(t["summary"] and t["sources"], t["id"])

    def test_timeline_is_dated_and_in_order(self):
        dates = [e["date"] for e in BOOK["timeline"]]
        self.assertEqual(dates, sorted(dates))
        for e in BOOK["timeline"]:
            self.assertRegex(e["date"], DATE)
            self.assertRegex(e["url"], URL)
            self.assertTrue(e["title"] and e["what"], e["title"])


if __name__ == "__main__":
    unittest.main()

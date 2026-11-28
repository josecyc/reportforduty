"""The map of needs (site/map.json) and the Futuras views reader (rfd/views.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from rfd import intel, views
from rfd.registry import PROGRAMS_DIR

ROOT = Path(__file__).resolve().parent.parent
MAP = json.loads((ROOT / "site" / "map.json").read_text(encoding="utf-8"))
KINDS = {"audit", "wargame", "frontier", "intel", "training", "guide", "gallery", "arena"}


def all_texts():
    for need in MAP["needs"].values():
        yield from need["texts"]
    for step in MAP["argument"]:
        yield from step["texts"]
    for level in MAP["reading"]:
        yield from level["items"]


class MapIntegrity(unittest.TestCase):
    def test_every_need_is_in_exactly_one_region(self):
        placed = [n for r in MAP["regions"] for n in r["needs"]]
        self.assertEqual(sorted(placed), sorted(MAP["needs"]))
        self.assertEqual(len(placed), len(set(placed)))

    def test_references_resolve(self):
        lean_programs = {p.stem for p in PROGRAMS_DIR.glob("*.json")}
        for nid, need in MAP["needs"].items():
            for t in need["terms"]:
                self.assertIn(t, MAP["terms"], f"{nid}: unknown term {t}")
            for d in need["views"]:
                self.assertIn(d, intel.SCALES, f"{nid}: unknown Futuras question {d}")
            for th in need["theaters"]:
                self.assertIn(th["kind"], KINDS, nid)
                if "program" in th:
                    self.assertIn(th["program"], lean_programs, nid)
        for step in MAP["argument"]:
            for n in step["needs"]:
                self.assertIn(n, MAP["needs"])
            if step["view"]:
                self.assertIn(step["view"], intel.SCALES)

    def test_needs_without_a_mission_say_what_a_judge_would_need(self):
        for nid, need in MAP["needs"].items():
            if not need["theaters"]:
                self.assertTrue(need["judge_needed"].strip(), f"{nid} has no mission and no explanation")

    def test_every_source_is_a_public_https_link_with_a_year(self):
        for t in all_texts():
            self.assertTrue(t["url"].startswith("https://"), t["url"])
            self.assertIsInstance(t["year"], int, t["title"])
            self.assertTrue(t["title"] and t["authors"], t)

    def test_every_term_is_used_somewhere(self):
        used = {t for need in MAP["needs"].values() for t in need["terms"]}
        self.assertEqual(set(MAP["terms"]) - used, set())


TS = '''export const VIEWS_AS_OF = "2026-01-02";
export const DIMENSIONS: Dimension[] = [
  {
    id: "pace",
    group: "want",
    question: "How fast: should it go?",
    short: "Pace",
    kind: "ordinal",
    points: [
      { value: 1, label: "Race: as fast as possible, to win", short: "Race" },
      { value: 2, label: "Stop, by treaty", short: "Stop" }, // trailing comment
    ],
  },
];
'''


class ViewsReader(unittest.TestCase):
    def test_literal_parser_handles_bare_keys_colons_in_strings_and_trailing_commas(self):
        as_of, dims = views.parse_dimensions(TS)
        self.assertEqual(as_of, "2026-01-02")
        self.assertEqual(dims[0]["question"], "How fast: should it go?")
        self.assertEqual([p["value"] for p in dims[0]["points"]], [1, 2])

    def test_parser_refuses_code(self):
        with self.assertRaises(views.ViewsError):
            views.js_literal_to_json('[{ id: require("fs") }]')

    def test_current_placement_is_the_most_recent_statement(self):
        data = {
            "people": [{"id": "a", "name": "Ann", "short": "Ann"}],
            "statements": [{"id": "s-new", "date": "2025-06"}, {"id": "s-old", "date": "2023"}],
            "stances": [
                {"statement": "s-new", "person": "a", "dimension": "pace", "status": "stated", "value": 2},
                {"statement": "s-old", "person": "a", "dimension": "pace", "status": "stated", "value": 1},
            ],
        }
        cur = views.current_placements(data)
        self.assertEqual(cur["pace"][0]["value"], 2)
        self.assertEqual(cur["pace"][0]["date"], "2025-06")

    def test_load_reads_a_futuras_folder_and_is_none_without_one(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(views.load(Path(d)))
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "views.ts").write_text(TS)
            (Path(d) / "lib" / "views.json").write_text(json.dumps({
                "people": [{"id": "a", "name": "Ann", "short": "Ann"}],
                "statements": [{"id": "s", "date": "2025"}],
                "stances": [{"statement": "s", "person": "a", "dimension": "pace", "status": "stated", "value": 1}],
                "allegations": []}))
            snap = views.load(Path(d))
            self.assertEqual(snap["as_of"], "2026-01-02")
            self.assertEqual(snap["current"]["pace"][0]["name"], "Ann")

    def test_real_futuras_parses_if_present(self):
        from rfd import settings
        fut = settings.path_setting("RFD_FUTURAS", "futuras_dir")
        if not fut or not (fut / "lib" / "views.ts").exists():
            self.skipTest("Futuras not on this machine")
        snap = views.load(fut)
        self.assertIsNotNone(snap)
        self.assertEqual({d["id"] for d in snap["dimensions"]}, set(intel.SCALES))


if __name__ == "__main__":
    unittest.main()

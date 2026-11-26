"""The record of efforts (site/efforts.json): who is doing what on AI safety, and the map's frame."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = json.loads((ROOT / "site" / "map.json").read_text(encoding="utf-8"))
EFFORTS = json.loads((ROOT / "site" / "efforts.json").read_text(encoding="utf-8"))
KINDS = {"developer", "government", "research", "policy", "watchdog", "funder", "training", "industry"}
COMMITMENTS = {"seoul", "eu-code", "eu-code-safety", "fmf", "sb53"}
INSTRUMENT_KINDS = {"law", "treaty", "commitment", "declaration", "report", "consensus", "body"}
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class Frame(unittest.TestCase):
    def test_every_region_is_under_exactly_one_axis(self):
        placed = [r for a in MAP["axes"] for r in a["regions"]]
        self.assertEqual(sorted(placed), sorted(r["id"] for r in MAP["regions"]))
        self.assertEqual(len(placed), len(set(placed)))

    def test_regions_are_numbered_in_axis_order(self):
        order = [r for a in MAP["axes"] for r in a["regions"]]
        self.assertEqual([r["id"] for r in MAP["regions"]], order)
        self.assertEqual([r["n"] for r in MAP["regions"]], list(range(1, len(order) + 1)))

    def test_quotes_point_at_sources(self):
        for q in MAP["frame"]["quotes"]:
            self.assertLess(q["source"], len(MAP["frame"]["sources"]))
            self.assertTrue(q["text"].strip())


class Record(unittest.TestCase):
    def test_ids_are_unique_slugs(self):
        ids = [o["id"] for o in EFFORTS["orgs"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^[a-z0-9][a-z0-9-]*$")

    def test_every_org_is_well_formed(self):
        for o in EFFORTS["orgs"]:
            self.assertIn(o["kind"], KINDS, o["id"])
            self.assertTrue(o["name"] and o["what"], o["id"])
            self.assertTrue(o["url"].startswith("https://"), o["id"])
            if o["kind"] != "developer":
                self.assertIsNone(o.get("framework"), f"{o['id']}: only developers have frameworks")
                self.assertEqual(o.get("commitments", []), [], o["id"])
            if o.get("framework"):
                fw = o["framework"]
                self.assertTrue(fw["url"].startswith("https://"), o["id"])
                self.assertTrue(fw["name"] and fw["summary"], o["id"])
                if fw.get("date"):
                    self.assertRegex(fw["date"], DATE, o["id"])
            for c in o.get("commitments", []):
                self.assertIn(c["id"], COMMITMENTS, o["id"])
                self.assertTrue(c["url"].startswith("https://"), o["id"])

    def test_every_effort_has_a_source_and_valid_needs(self):
        for o in EFFORTS["orgs"]:
            for e in o["efforts"]:
                self.assertTrue(e["url"].startswith("https://"), f"{o['id']}: {e['title']}")
                self.assertTrue(e["title"] and e["what"], o["id"])
                for n in e["needs"]:
                    self.assertIn(n, MAP["needs"], f"{o['id']}: {e['title']}")

    def test_instruments(self):
        ids = [i["id"] for i in EFFORTS["instruments"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in EFFORTS["instruments"]:
            self.assertIn(i["kind"], INSTRUMENT_KINDS, i["id"])
            self.assertTrue(i["url"].startswith("https://"), i["id"])
            if i.get("date"):
                self.assertRegex(i["date"], DATE, i["id"])
            for n in i["needs"]:
                self.assertIn(n, MAP["needs"], i["id"])

    def test_ratings_name_companies_in_the_record(self):
        orgs = {o["id"] for o in EFFORTS["orgs"]}
        for r in EFFORTS["ratings"]:
            self.assertTrue(r["url"].startswith("https://"), r["source"])
            for s in r["scores"]:
                if s.get("org"):
                    self.assertIn(s["org"], orgs, s)

    def test_every_need_on_the_map_is_reachable(self):
        # Not a coverage claim: a need nobody works on is shown as such. This only checks the
        # record is wired to the map at all.
        tagged = {n for o in EFFORTS["orgs"] for e in o["efforts"] for n in e["needs"]}
        self.assertGreater(len(tagged & set(MAP["needs"])), len(MAP["needs"]) // 2)


if __name__ == "__main__":
    unittest.main()

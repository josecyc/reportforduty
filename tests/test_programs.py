"""Programs (site/programs.json) and the plan builder's content (map.json "plan")."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = json.loads((ROOT / "site" / "map.json").read_text(encoding="utf-8"))
PROGRAMS = json.loads((ROOT / "site" / "programs.json").read_text(encoding="utf-8"))
KINDS = {"course", "fellowship", "bootcamp", "grant", "event", "job-board", "advising", "community"}
FOR = {"ml", "swe", "theory", "policy", "media", "ops", "student", "other"}
TIME = {"taste", "week", "career"}
STATUS = {"open", "upcoming", "rolling", "closed", "unknown"}
DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def map_titles():
    titles = {t["title"] for n in MAP["needs"].values() for t in n["texts"]}
    return titles | {t["title"] for lv in MAP["reading"] for t in lv["items"]}


class Plan(unittest.TestCase):
    def test_backgrounds_and_times_match_the_program_vocabulary(self):
        self.assertEqual({b["id"] for b in MAP["plan"]["backgrounds"]}, FOR)
        self.assertEqual({t["id"] for t in MAP["plan"]["times"]}, TIME)

    def test_plan_readings_are_texts_already_on_the_map(self):
        titles = map_titles()
        for b in MAP["plan"]["backgrounds"]:
            for t in b["read"]:
                self.assertIn(t, titles, b["id"])
            for n in b["needs"]:
                self.assertIn(n, MAP["needs"], b["id"])
            self.assertTrue(b["first"].strip() and b["who"].strip(), b["id"])


class Programs(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [p["id"] for p in PROGRAMS["programs"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_program_is_well_formed(self):
        for p in PROGRAMS["programs"]:
            self.assertIn(p["kind"], KINDS, p["id"])
            self.assertTrue(p["url"].startswith("https://"), p["id"])
            self.assertTrue(p["name"] and p["what"], p["id"])
            self.assertTrue(set(p["for"]) <= FOR and p["for"], p["id"])
            self.assertTrue(set(p["time"]) <= TIME and p["time"], p["id"])
            for n in p.get("needs", []):
                self.assertIn(n, MAP["needs"], p["id"])
            d = p["dates"]
            self.assertIn(d["status"], STATUS, p["id"])
            for k in ("deadline", "opens", "starts"):
                if d.get(k):
                    self.assertRegex(d[k], DATE, f"{p['id']} {k}")

    def test_an_open_program_has_a_future_deadline_or_says_it_is_open_without_one(self):
        as_of = PROGRAMS["as_of"]
        for p in PROGRAMS["programs"]:
            d = p["dates"]
            if d["status"] == "open" and d.get("deadline"):
                self.assertGreaterEqual(d["deadline"], as_of, f"{p['id']} is marked open with a past deadline")


if __name__ == "__main__":
    unittest.main()

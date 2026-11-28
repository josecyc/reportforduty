"""The futures gallery: site/futures.json and submissions reviewed by a person (rfd/media.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from rfd import desk as deskmod

ROOT = Path(__file__).resolve().parent.parent
FUT = json.loads((ROOT / "site" / "futures.json").read_text(encoding="utf-8"))
MAP = json.loads((ROOT / "site" / "map.json").read_text(encoding="utf-8"))
TONES = {"hopeful", "cautionary", "mixed"}


class Gallery(unittest.TestCase):
    def test_twelve_scenarios_with_unique_ids(self):
        ids = [s["id"] for s in FUT["scenarios"]]
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(ids), len(set(ids)))

    def test_works_are_well_formed(self):
        ids = {s["id"] for s in FUT["scenarios"]}
        seen = set()
        for w in FUT["works"]:
            self.assertNotIn(w["id"], seen)
            seen.add(w["id"])
            self.assertIn(w["tone"], TONES, w["id"])
            self.assertTrue(w["url"].startswith("https://"), w["id"])
            self.assertTrue(w["title"] and w["creator"] and w["premise"], w["id"])
            if w.get("scenario"):
                self.assertIn(w["scenario"], ids, w["id"])

    def test_balance_across_tones(self):
        counts = {t: sum(1 for w in FUT["works"] if w["tone"] == t) for t in TONES}
        self.assertTrue(all(c >= 4 for c in counts.values()), counts)

    def test_the_imagine_need_points_at_the_gallery(self):
        self.assertIn({"kind": "gallery"}, MAP["needs"]["imagine"]["theaters"])


class AfterWork(unittest.TestCase):
    A = FUT["after_work"]

    def test_plans_are_well_formed(self):
        qs = {q["id"] for q in self.A["questions"]}
        self.assertEqual(qs, {"income", "ownership", "power", "meaning", "transition"})
        seen = set()
        for p in self.A["plans"]:
            self.assertNotIn(p["id"], seen)
            seen.add(p["id"])
            self.assertIn(p["kind"], {"plan", "vision", "pilot", "analysis", "warning"}, p["id"])
            self.assertTrue(p["answers"] and set(p["answers"]) <= qs, p["id"])
            self.assertRegex(p["url"], r"^https?://", p["id"])
            self.assertTrue(p["name"] and p["who"] and p["mechanism"] and p["status"], p["id"])
            self.assertLessEqual(len(p["quote"].split()), 30, p["id"])
            for c in p["critiques"]:
                self.assertRegex(c["url"], r"^https?://", p["id"])
                self.assertTrue(c["who"] and c["what"], p["id"])
        for e in self.A["evidence"]:
            self.assertRegex(e["url"], r"^https?://", e["id"])
            self.assertTrue(e["finding"], e["id"])
        self.assertGreaterEqual(len(self.A["plans"]), 25)


class Submissions(unittest.TestCase):
    def setUp(self):
        self.desk = deskmod.Desk(Path(tempfile.mkdtemp(prefix="rfd-media-")) / "desk.db", merge=False, worker=False)

    def body(self, **kw):
        b = {"title": "After the Minds", "creator": "A. Maker", "url": "https://example.org/video", "medium": "video",
             "tone": "hopeful", "premise": "A city where people and AI systems share decisions in the open.",
             "assumes": "Interpretability and verification arrived before the most capable systems.", "scenario": "",
             "ai_generated": True, "contact": "maker@example.org", "rights": True, "labelled": True, "likeness": True}
        b.update(kw)
        return json.dumps(b).encode()

    def test_refuses_without_the_three_confirmations_or_with_bad_fields(self):
        for kw, word in [({"rights": False}, "rights"), ({"labelled": False}, "labelled"), ({"likeness": False}, "likeness"),
                         ({"url": "http://x.org/v"}, "url"), ({"tone": "grim"}, "tone"), ({"scenario": "nope"}, "scenario"),
                         ({"title": "<b>x</b>"}, "title")]:
            code, out = self.desk.media.submit(self.body(**kw))
            self.assertEqual(code, 422, kw)
            self.assertTrue(any(word in r for r in out["reasons"]), (kw, out["reasons"]))

    def test_only_approved_work_is_shown_and_the_contact_never_is(self):
        code, out = self.desk.media.submit(self.body())
        self.assertEqual(code, 202, out)
        self.assertEqual(self.desk.media.state()["works"], [])
        self.assertEqual(self.desk.media.state()["pending_review"], 1)
        self.assertTrue(self.desk.media.review(out["submission"], True)[0])
        st = self.desk.state()
        self.assertEqual(st["media"]["works"][0]["title"], "After the Minds")
        self.assertNotIn("maker@example.org", json.dumps(st))


if __name__ == "__main__":
    unittest.main()

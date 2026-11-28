"""The debate arena: ratings, the round check, slot order, the desk flow, the verdict tally, and the
committed arena files.

    python3 -m unittest tests.test_arena -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from rfd import arena
from rfd import desk as deskmod

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import arena as arena_tool  # noqa: E402  (tools/arena.py)

PAGE = """<html><head><style>.x{}</style><script>var q = "Interpretability is hopeless";</script></head>
<body><p>Mechanistic   interpretability aims to <b>reverse&#8209;engineer</b> neural networks into
human&nbsp;understandable algorithms.</p><p>We call it &ldquo;AI control&rdquo;: safety despite intentional subversion.</p></body></html>"""


def fake_fetch(url):
    if url == "https://example.org/missing":
        raise OSError("404")
    return PAGE


def good(debate="D1", idea="interp", rnd="opening", n=120, sources=2):
    return {"kind": "debate", "debate": debate, "idea": idea, "round": rnd, "model": "test-model",
            "text": " ".join(["word"] * n),
            "sources": [{"title": "A page", "url": f"https://example.org/{i}",
                         "quote": "aims to reverse-engineer neural networks into human understandable algorithms"}
                        for i in range(sources)]}


class Ratings(unittest.TestCase):
    def test_no_games_is_1500(self):
        r = arena.bradley_terry([], ["a", "b"])
        self.assertAlmostEqual(r["a"]["rating"], 1500)
        self.assertAlmostEqual(r["b"]["rating"], 1500)
        self.assertGreater(r["a"]["se"], 200)

    def test_winner_rises_symmetrically(self):
        r = arena.bradley_terry([("a", "b", 1.0)] * 8 + [("b", "a", 1.0)] * 2, ["a", "b"])
        self.assertGreater(r["a"]["rating"], 1550)
        self.assertAlmostEqual(r["a"]["rating"] - 1500, 1500 - r["b"]["rating"], places=6)
        self.assertLess(r["a"]["se"], arena.bradley_terry([], ["a"])["a"]["se"])

    def test_ties_stay_level_and_unbeaten_stays_finite(self):
        r = arena.bradley_terry(arena._games([("a", "b", "even")] * 5), ["a", "b"])
        self.assertAlmostEqual(r["a"]["rating"], r["b"]["rating"], places=6)
        r = arena.bradley_terry([("a", "b", 1.0)] * 50, ["a", "b"])
        self.assertLess(r["a"]["rating"], 2500)


class RoundCheck(unittest.TestCase):
    cfg = arena.load()

    def test_good_round_passes(self):
        self.assertEqual(arena.validate(good(), "D1-interp-opening", self.cfg), [])

    def test_limits(self):
        self.assertTrue(any("words" in p for p in arena.validate(good(n=20), "D1-interp-opening", self.cfg)))
        self.assertTrue(any("words" in p for p in arena.validate(good(n=400), "D1-interp-opening", self.cfg)))
        self.assertTrue(any("sources" in p for p in arena.validate(good(sources=1), "D1-interp-opening", self.cfg)))
        self.assertEqual(arena.validate(good(rnd="rebuttal", n=100, sources=0), "D1-interp-rebuttal", self.cfg), [])
        self.assertTrue(arena.validate(good(idea="control"), "D1-interp-opening", self.cfg))   # wrong slot
        bad = good(); bad["sources"][0]["url"] = "http://example.org/"
        self.assertTrue(any("https" in p for p in arena.validate(bad, "D1-interp-opening", self.cfg)))

    def test_quotes_found_through_markup_entities_and_curly_quotes(self):
        sub = good()
        sub["sources"][1]["quote"] = 'We call it "AI control": safety despite intentional subversion.'
        r = arena.check_quotes(sub, fake_fetch)
        self.assertTrue(r["ok"], r["summary"])

    def test_missing_quote_or_page_fails(self):
        sub = good()
        sub["sources"][1]["quote"] = "Interpretability is hopeless and should be abandoned now"   # only inside <script>
        self.assertFalse(arena.check_quotes(sub, fake_fetch)["ok"])
        sub = good(); sub["sources"][0]["url"] = "https://example.org/missing"
        r = arena.check_quotes(sub, fake_fetch)
        self.assertFalse(r["ok"])
        self.assertIn("could not read", r["summary"])


class DeskFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rfd-arenatest-"))
        (self.tmp / "arena").mkdir()
        shutil.copy(ROOT / "arena" / "debates.json", self.tmp / "arena" / "debates.json")
        self.desk = deskmod.Desk(self.tmp / "db" / "desk.db", merge=False, worker=False)
        self.desk.arena_root = self.tmp / "arena"
        self.desk.fetcher = fake_fetch

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def take_and_write(self, handle, slot=None):
        code, out = self.desk.next(handle, None, None if slot else "arena", False, False, None, slot)
        self.assertEqual(code, 200, out)
        brief = out["debate"]
        did, idea, rnd = arena.SLOT.match(brief["id"]).groups()
        sub = good(did, idea, rnd, n=150 if rnd == "opening" else 90, sources=2 if rnd == "opening" else 1)
        code, res = self.desk.submit(out["lease"]["id"], json.dumps(sub).encode())
        self.assertEqual(code, 202, res)
        self.desk._check_one(res["submission"])
        return brief, self.desk.submission(res["submission"])[1]

    def test_a_debate_runs_openings_then_rebuttals_then_judging(self):
        b1, s1 = self.take_and_write("alice")
        self.assertEqual(b1["id"], "D1-interp-opening")
        self.assertEqual(s1["verdict"], "ACCEPTED", s1)
        self.assertTrue((self.tmp / s1["result"]["file"]).exists())
        rec = json.loads((self.tmp / s1["result"]["file"]).read_text())
        self.assertEqual(rec["by"], "alice")
        # alice may not argue the other side of D1; she is sent on to D2
        code, out = self.desk.next("alice", None, "arena", False, False)
        self.assertEqual(out["debate"]["debate"], "D2")
        self.desk.release(out["lease"]["id"], "other")
        code, out = self.desk.next("alice", None, None, False, False, None, "D1-control-opening")
        self.assertEqual(code, 409)
        # the rebuttal slot opens only after both openings, and shows the other side's opening
        b2, _ = self.take_and_write("bob", "D1-control-opening")
        code, out = self.desk.next("bob", None, None, False, False, None, "D1-control-rebuttal")
        self.assertEqual(code, 200, out)
        self.assertEqual(out["debate"]["their_opening"]["by"], "alice")
        self.desk.release(out["lease"]["id"], "other")
        self.take_and_write("alice", "D1-interp-rebuttal")
        self.take_and_write("bob", "D1-control-rebuttal")
        st = self.desk.state()["arena"]
        d1 = next(d for d in st["debates"] if d["id"] == "D1")
        self.assertEqual(d1["status"], "judging")
        self.assertEqual(d1["advocates"], {"interp": ["alice"], "control": ["bob"]})
        # verdicts move the ratings: ideas and advocates separately
        (self.tmp / "arena" / "verdicts.json").write_text(json.dumps({"verdicts": [
            {"issue": 1, "debate": "D1", "idea": "second", "argued": "first", "before": "first"},
            {"issue": 2, "debate": "D1", "idea": "second", "argued": "first", "before": "none"},
            {"issue": 3, "debate": "D2", "idea": "first", "argued": "first", "before": "none"}]}))
        st = self.desk.state()["arena"]
        ideas = {r["id"]: r for r in st["standings"]["ideas"]}
        self.assertGreater(ideas["control"]["rating"], ideas["interp"]["rating"])
        self.assertEqual(ideas["prove"]["verdicts"], 0)          # D2 is not finished, so it does not count
        adv = {r["handle"]: r for r in st["standings"]["advocates"]}
        self.assertGreater(adv["alice"]["rating"], adv["bob"]["rating"])
        self.assertEqual(st["standings"]["debates"]["D1"]["changed"], 1)

    def test_a_failed_quote_writes_nothing(self):
        code, out = self.desk.next("carol", None, "arena", False, False)
        sub = good(); sub["sources"][0]["quote"] = "words that are on no page anywhere at all"
        code, res = self.desk.submit(out["lease"]["id"], json.dumps(sub).encode())
        self.desk._check_one(res["submission"])
        s = self.desk.submission(res["submission"])[1]
        self.assertEqual(s["verdict"], "REJECTED")
        self.assertFalse((self.tmp / "arena" / "rounds").exists())


class Tally(unittest.TestCase):
    BODY = ("### Debate\n\nd1\n\n### Before reading, which idea did you favor?\n\nNo view\n\n"
            "### Which idea should get the push?\n\nThe second idea\n\n### Which side argued better?\n\nEven\n\n"
            "### What decided it?\n\n_No response_\n")

    def issue(self, n, login, when="2026-12-01T10:00:00Z", **kw):
        return {"number": n, "created_at": when, "body": self.BODY, "user": {"login": login, "type": "User"}} | kw

    def test_parse(self):
        f = arena_tool.parse_body(self.BODY)
        self.assertEqual(f["debate"], "d1")
        self.assertEqual(f["why"], "")
        v = arena_tool.verdict_from(self.issue(5, "x"), {"D1"})
        self.assertEqual((v["debate"], v["idea"], v["argued"], v["before"]), ("D1", "second", "even", "none"))

    def test_rules(self):
        born = {"old": "2020-01-01T00:00:00Z", "new": "2026-11-20T00:00:00Z"}
        issues = [self.issue(1, "old"), self.issue(2, "OLD", "2026-12-02T00:00:00Z"), self.issue(3, "new"),
                  self.issue(4, "spam", state_reason="not_planned"), self.issue(5, "bot") | {"user": {"login": "b", "type": "Bot"}},
                  self.issue(6, "old") | {"pull_request": {}}]
        vs, skipped = arena_tool.select(issues, {"D1"}, lambda login: born.get(login.lower(), "2019-01-01T00:00:00Z"))
        self.assertEqual([v["issue"] for v in vs], [1])
        self.assertEqual(skipped["repeat"], 1)
        self.assertEqual(skipped["young_account"], 1)
        self.assertEqual(skipped["not_planned"], 1)
        self.assertEqual(skipped["bot"], 1)
        self.assertNotIn("old", json.dumps(vs))                  # no logins are stored


class CommittedArena(unittest.TestCase):
    def test_files_are_consistent(self):
        cfg = arena.load()
        needs = json.loads((ROOT / "site" / "map.json").read_text())["needs"]
        ids = [i["id"] for i in cfg["ideas"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in cfg["ideas"]:
            self.assertIn(i["need"], needs, i["id"])
            self.assertTrue(i["source"]["url"].startswith("https://"))
            self.assertRegex(i["id"], r"^[a-z0-9-]{1,40}$")
        dids = [d["id"] for d in cfg["debates"]]
        self.assertEqual(len(dids), len(set(dids)))
        for d in cfg["debates"]:
            self.assertEqual(len(set(d["ideas"])), 2)
            self.assertTrue(set(d["ideas"]) <= set(ids))
        for f in sorted((ROOT / "arena" / "rounds").glob("*/*.json")):
            r = json.loads(f.read_text())
            slot = f"{r['debate']}-{r['idea']}-{r['round']}"
            self.assertEqual(f.relative_to(ROOT / "arena" / "rounds").as_posix(), f"{r['debate']}/{r['idea']}-{r['round']}.json")
            self.assertIn(r["debate"], dids)
            self.assertEqual(arena.validate(r, slot, cfg), [], f)
            self.assertTrue(r.get("by"), f)
        for v in arena.verdicts():
            self.assertIn(v["debate"], dids)
        self.assertIsNotNone(arena.public_state())


if __name__ == "__main__":
    unittest.main()

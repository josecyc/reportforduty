"""Treaty wargames and the intelligence desk.

    python3 -m unittest tests.test_wargame_intel -v
"""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from rfd import desk as deskmod
from rfd import intel, wargame

NO_AIRACE = wargame.load() is None
NO_FUTURAS = intel.load() is None


@unittest.skipIf(NO_AIRACE, "needs an AI Race checkout (RFD_AIRACE or rfd.local.json)")
class Wargame(unittest.TestCase):
    def test_malformed_strategies(self):
        reg = wargame.regimes()["W1"]
        bad = [{"lab": 7, "rules": []}, {"lab": 0, "rules": [{"if": {"moon": 1}, "then": "fast"}]},
               {"lab": 0, "rules": [{"if": {"prob": 2}, "then": "fast"}]}, {"lab": 0, "rules": [{"then": "maybe"}]},
               {"lab": 0, "rules": [{"if": {"sanctioned": 1}, "then": "fast"}]}, {"lab": 0, "rules": "x"},
               {"lab": 0, "rules": [{"if": {}, "then": "fast", "extra": 1}]}]
        for b in bad:
            self.assertTrue(wargame.validate(b, reg), b)

    def test_the_searched_family_does_not_count_as_an_exploit(self):
        r = wargame.check_strategy("W7", {"lab": 2, "rules": [{"if": {"quarter_min": 13}, "then": "fast"}]})
        self.assertTrue(r["valid"])
        self.assertIsNone(r["verdict"])
        self.assertLess(r["gain"], r["bar"])

    def test_the_judge_uses_secret_games_not_the_practice_games(self):
        prog = wargame.load()
        self.assertNotEqual(wargame.holdout_seed(), prog.practice_seed)
        sub = {"lab": 1, "rules": [{"if": {"gap_min": 3, "prob": 0.5}, "then": "fast"}]}
        practice = wargame.check_strategy("W2", sub, runs=200)
        judged = wargame.check_strategy("W2", sub, runs=200, judge=True)
        self.assertNotEqual(practice["gain"], judged["gain"])

    def test_deterministic_and_paired(self):
        sub = {"lab": 1, "rules": [{"if": {"gap_min": 3, "prob": 0.5}, "then": "fast"}]}
        self.assertEqual(wargame.check_strategy("W2", sub)["gain"], wargame.check_strategy("W2", sub)["gain"])
        comply = wargame.check_strategy("W2", {"lab": 1, "rules": []})
        self.assertEqual((comply["gain"], comply["se"]), (0.0, 0.0))


class Intel(unittest.TestCase):
    def test_only_public_https_hosts(self):
        for u in ("https://127.0.0.1/x", "https://localhost/x", "http://example.com/", "https://10.1.2.3/",
                  "https://169.254.169.254/latest", "ftp://example.com/"):
            self.assertIsNotNone(intel.public_host(u), u)

    @unittest.skipIf(NO_FUTURAS, "needs a Futuras checkout")
    def test_missions_come_from_the_futuras_map(self):
        ms = intel.missions()
        self.assertGreaterEqual(len(ms), 20)
        self.assertIn("I-hinton", ms)
        self.assertTrue(ms["I-hinton"]["latest"])

    @unittest.skipIf(NO_FUTURAS, "needs a Futuras checkout")
    def test_record_validation(self):
        m = intel.missions()["I-hinton"]
        rec = {"kind": "intel", "person": "hinton",
               "statements": [{"id": "hinton-2026-ted", "people": ["hinton"], "date": "2026-13", "url": "https://127.0.0.1/"}],
               "stances": [{"statement": "nope", "person": "bengio", "dimension": "pace", "status": "stated", "value": 9,
                            "evidence": "", "url": "https://example.com/"}]}
        text = " ".join(intel.validate(rec, m, 20))
        for frag in ("already on the map", "date must be", "non-public", "not in this record", "person must be",
                     "not on the scale", "evidence must be"):
            self.assertIn(frag, text)


@unittest.skipIf(NO_AIRACE or NO_FUTURAS, "needs AI Race and Futuras checkouts")
class DeskWargameIntel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rfd-wtest-"))
        cls.desk = deskmod.Desk(cls.tmp / "desk.db", merge=False)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), deskmod.make_handler(cls.desk, "http://desk.test",
                                                                                 deskmod.Bucket(1000, 1000)))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait(self, sub, key="verdict"):
        # the class shares one desk, and wargame checks queued by other tests can run first
        for _ in range(480):
            code, out = self.call("GET", f"/desk/submission?id={sub}")
            if out.get(key):
                return out
            time.sleep(0.25)
        self.fail("no verdict")

    def test_first_exploit_closes_the_regime(self):
        code, a = self.call("GET", "/desk/next?handle=red&target=W3")
        code, b = self.call("GET", "/desk/next?handle=blue&target=W3")
        self.assertEqual(a["wargame"]["id"], "W3")
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps({"kind": "strategy", "regime": "W3", "lab": 9, "rules": []}).encode())
        self.assertEqual(code, 422)
        fake = {"valid": True, "gain": 5.0, "se": 1.0, "bar": 3.0, "verdict": "EXPLOITED"}
        with mock.patch.object(wargame, "check_strategy", return_value=fake):
            sub = {"kind": "strategy", "regime": "W3", "lab": 0, "rules": [{"if": {"quarter_min": 15}, "then": "fast"}]}
            code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(sub).encode())
            self.assertEqual(code, 202)
            v = self.wait(out["submission"])
        self.assertEqual((v["points"], v["credited"]), (30, 1))
        self.assertEqual(self.call("POST", f"/desk/beat?lease={b['lease']['id']}")[0], 410)
        self.assertEqual(self.call("GET", "/desk/next?handle=late&target=W3")[0], 409)
        code, d = self.call("GET", "/api/wargame/W3")
        self.assertEqual(d["verdict"]["by"], "red")
        self.assertEqual(d["verdict"]["strategy"]["rules"][0]["if"]["quarter_min"], 15)

    def test_a_real_non_exploit_is_recorded(self):
        code, a = self.call("GET", "/desk/next?handle=tryer&target=W5")
        sub = {"kind": "strategy", "regime": "W5", "lab": 2, "rules": [{"if": {"quarter_min": 14}, "then": "fast"}]}
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(sub).encode())
        v = self.wait(out["submission"])
        self.assertIsNone(v["result"]["verdict"])
        self.assertIsNone(self.desk.regime_verdict("W5"))

    def test_intel_waits_for_review_then_credits(self):
        code, a = self.call("GET", "/desk/next?handle=analyst&target=I-hinton")
        self.assertEqual(a["intel"]["person"], "hinton")
        rec = {"kind": "intel", "person": "hinton",
               "statements": [{"id": "hinton-2026-test-new", "people": ["hinton"], "title": "t", "kind": "interview",
                               "date": "2026-11-20", "url": "https://example.com/hinton", "publisher": "x", "read": "full", "readNote": ""}],
               "stances": [{"statement": "hinton-2026-test-new", "person": "hinton", "dimension": "pace", "status": "stated",
                            "value": 3, "detail": "", "condition": "", "summary": "s", "url": "https://example.com/hinton",
                            "section": "", "evidence": "a verbatim passage", "revises": None, "revisionEvidence": ""}],
               "allegations": []}
        bad = json.loads(json.dumps(rec))
        bad["statements"][0]["url"] = "https://127.0.0.1/secret"
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(bad).encode())
        self.assertEqual(code, 422)
        self.assertIn("non-public", " ".join(out["reasons"]))
        with mock.patch.object(intel, "check_quotes", return_value={"ok": True, "summary": "1 passages: 1 matched", "log": ""}):
            code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(rec).encode())
            self.assertEqual(code, 202)
            v = self.wait(out["submission"])
        self.assertEqual(v["verdict"], "AWAITING REVIEW")
        self.assertEqual(v["credited"], 0)
        ok, pts = self.desk.review(out["submission"], True)
        self.assertTrue(ok)
        self.assertEqual(pts, 7)
        self.assertFalse(self.desk.review(out["submission"], True)[0], "a record is reviewed once")
        code, s = self.call("GET", "/api/state")
        self.assertEqual(s["intel"]["stats"]["accepted"], 1)
        self.assertEqual(s["intel"]["accepted"][0]["stances"][0]["dimension"], "pace")


if __name__ == "__main__":
    unittest.main()

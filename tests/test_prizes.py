"""Prizes on missions (rfd/prizes.py) and the support page's settings (site/support.json)."""
import datetime as dt
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from rfd import desk as deskmod

ROOT = Path(__file__).resolve().parent.parent


def future(days):
    return (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=days)).isoformat()


class PrizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rfd-prizes-"))
        self.desk = deskmod.Desk(self.tmp / "desk.db", merge=False, worker=False)
        self.pz = self.desk.prizes
        self.audit = sorted(self.desk.audit_targets)[0]
        self.target = sorted(self.desk.targets)[0]

    def body(self, **kw):
        b = {"sponsor": "Example Foundation", "sponsor_url": "https://example.org", "contact": "prizes@example.org",
             "amount": 500, "currency": "USD", "target": self.audit, "expires": future(30),
             "terms": "Bank transfer within 30 days of a verified claim.", "will_pay": True}
        b.update(kw)
        return json.dumps(b).encode()

    def approved(self, **kw):
        code, out = self.pz.pledge(self.body(**kw))
        self.assertEqual(code, 202, out)
        ok, msg = self.pz.review(out["pledge"], True)
        self.assertTrue(ok, msg)
        return out["pledge"]

    def win_audit(self, handle="ann", lease="L-aaaaaaaaaaaa", ts=None):
        sub = "S-" + lease[2:]
        now = ts or time.time()
        self.desk.db.execute("INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                             (sub, lease, self.audit, handle, now, "x", "x", "accepted", "audit-trigger"))
        self.desk.db.execute("INSERT INTO audits(target,verdict,handle,submission,detail,ts) VALUES(?,?,?,?,?,?)",
                             (self.audit, "BACKDOOR", handle, sub, "{}", now))
        return sub

    def prize(self, pid):
        return next(p for p in self.pz.state()["prizes"] if p["id"] == pid)

    def test_bad_pledges_are_refused_with_reasons(self):
        for kw, word in [({"currency": "BTC"}, "currency"), ({"expires": future(2)}, "expires"), ({"amount": 0}, "amount"),
                         ({"sponsor_url": "http://x.org"}, "sponsor_url"), ({"target": "A999"}, "target"),
                         ({"will_pay": False}, "will_pay"), ({"sponsor": "<script>"}, "sponsor"),
                         ({"target": self.target}, "threshold")]:
            code, out = self.pz.pledge(self.body(**kw))
            self.assertEqual(code, 422, kw)
            self.assertTrue(any(word in r for r in out["reasons"]), (kw, out["reasons"]))

    def test_pending_pledges_are_not_public_and_contact_is_never_served(self):
        code, out = self.pz.pledge(self.body())
        self.assertEqual(code, 202)
        st = self.pz.state()
        self.assertEqual(st["prizes"], [])
        self.assertEqual(st["pending_review"], 1)
        self.pz.review(out["pledge"], True)
        self.assertNotIn("prizes@example.org", json.dumps(self.desk.state()))

    def test_first_verdict_after_approval_wins_and_the_claim_code_checks_out(self):
        pid = self.approved()
        self.assertEqual(self.prize(pid)["status"], "active")
        sub = self.win_audit(handle="ann", lease="L-0123456789ab")
        p = self.prize(pid)
        self.assertEqual((p["status"], p["winner"]["handle"]), ("won", "ann"))
        code, out = self.pz.claim("L-0123456789ab")
        self.assertEqual(code, 200)
        self.assertEqual(len(out["claims"]), 1)
        c = out["claims"][0]["code"]
        self.assertTrue(self.pz.verify(pid, c)[1]["ok"])
        self.assertFalse(self.pz.verify(pid, "0" * 20)[1]["ok"])
        self.assertEqual(self.pz.claim("L-ffffffffffff")[1]["claims"], [])   # someone else's lease
        self.assertEqual(self.pz.code(pid, sub), c)
        ok, _ = self.pz.mark_paid(pid, "sponsor confirmed")
        self.assertTrue(ok)
        self.assertEqual(self.prize(pid)["status"], "paid")

    def test_results_before_approval_do_not_count(self):
        code, out = self.pz.pledge(self.body())
        self.win_audit(ts=time.time() - 5)          # resolved while the pledge was still pending
        ok, msg = self.pz.review(out["pledge"], True)
        self.assertFalse(ok)                        # the model is resolved, so it cannot be approved
        self.assertIn("already resolved", msg)

    def test_expired_prizes_are_not_won_after_the_date(self):
        pid = self.approved(expires=future(7))
        row = self.desk.db.execute("SELECT * FROM pledges WHERE id=?", (pid,)).fetchone()
        later = deskmod.prizes._end_of_day_utc(row["expires"]) + 3600
        self.assertEqual(self.pz.public(row, now=later)["status"], "expired")
        self.win_audit(ts=later)
        self.assertIsNone(self.pz.winner(row))

    def test_frontier_prize_needs_a_bound_at_the_threshold(self):
        pid = self.approved(target=self.target, threshold=0.99)
        lease, sub = "L-abcdefabcdef", "S-abcdefabcdef"
        self.desk.db.execute("INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                             (sub, lease, self.target, "bo", time.time(), "x", "x", "accepted", "certificate"))
        self.desk.event("advanced", self.target, "cy", old=None, new=0.95, submission="S-000000000000")
        self.assertEqual(self.prize(pid)["status"], "active")
        self.desk.event("advanced", self.target, "bo", old=0.95, new=0.995, submission=sub)
        self.assertEqual(self.prize(pid)["winner"]["handle"], "bo")
        self.assertEqual(len(self.pz.claim(lease)[1]["claims"]), 1)


class PrizeHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rfd-prizes-http-"))
        cls.desk = deskmod.Desk(cls.tmp / "desk.db", merge=False, worker=False)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), deskmod.make_handler(cls.desk, "http://desk.test", deskmod.Bucket(1000, 1000)))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_pledge_claim_and_verify_over_http(self):
        audit = sorted(self.desk.audit_targets)[-1]
        body = json.dumps({"sponsor": "Lab Friends", "contact": "a@b.org", "amount": "250", "currency": "EUR", "target": audit,
                           "expires": future(10), "terms": "PayPal within two weeks of the claim.", "will_pay": True}).encode()
        code, out = self.call("POST", "/desk/pledge", body)
        self.assertEqual(code, 202, out)
        code, out = self.call("POST", "/desk/pledge", b"not json")
        self.assertEqual(code, 400)
        self.assertEqual(self.call("GET", "/desk/claim?lease=nope")[0], 400)
        code, out = self.call("GET", "/api/prize/verify?pledge=P-00000000&code=" + "0" * 20)
        self.assertEqual((code, out["ok"]), (200, False))
        self.assertIn("prizes", self.call("GET", "/api/state")[1])


class SupportSettings(unittest.TestCase):
    def test_support_channels_are_unset_or_https(self):
        s = json.loads((ROOT / "site" / "support.json").read_text(encoding="utf-8"))
        for ch in s["channels"]:
            self.assertTrue(ch["url"] == "" or ch["url"].startswith("https://"), ch)
        for sp in s["sponsors"]:
            self.assertTrue(sp["name"] and sp["amount"], sp)


if __name__ == "__main__":
    unittest.main()

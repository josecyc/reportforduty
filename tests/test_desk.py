"""The desk end to end, over HTTP, with the real checker. Uses a temporary database and does
not merge accepted proofs into lean/.

    python3 -m unittest tests.test_desk -v
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

from rfd import desk as deskmod
from rfd import registry

LEAN_READY = (registry.LEAN_DIR / ".lake" / "packages" / "mathlib" / ".lake" / "build").exists()

HEAD = "import Mathlib.Basic.Real.Basic\n\nopen Classical\n\nnamespace ReportForDuty.Steps\n\n"
TAIL = "\n\nend ReportForDuty.Steps\n"


class DeskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rfd-desktest-"))
        cls.desk = deskmod.Desk(cls.tmp / "desk.db", merge=False)
        roomy = deskmod.Bucket(rate=1000, burst=1000)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), deskmod.make_handler(cls.desk, "http://desk.test", roomy))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, method, path, body=None, raw=False):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return r.status, (data if raw else json.loads(data or b"{}")), dict(r.headers)
        except urllib.error.HTTPError as e:
            data = e.read()
            try:
                return e.code, (data if raw else json.loads(data or b"{}")), dict(e.headers)
            except json.JSONDecodeError:
                return e.code, data, dict(e.headers)

    def take(self, handle, program="selftest", extra=""):
        code, out, _ = self.call("GET", f"/desk/next?handle={handle}&program={program}{extra}")
        self.assertEqual(code, 200, out)
        return out["gap"], out["lease"]

    def wait_verdict(self, sub_id, limit=300):
        t0 = time.time()
        while time.time() - t0 < limit:
            code, out, _ = self.call("GET", f"/desk/submission?id={sub_id}")
            if out.get("verdict"):
                return out
            time.sleep(1)
        self.fail("no verdict in time")

    def test_1_state_hides_selftest(self):
        code, s, _ = self.call("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual({p["id"] for p in s["programs"]}, {"offswitch", "rewardhacking", "retargeting"})
        self.assertEqual(s["totals"]["steps"], 23)
        self.assertEqual(self.call("GET", "/api/step/TEST-01")[0], 404)
        code, d, _ = self.call("GET", "/api/step/OSG-01")
        self.assertEqual(code, 200)
        self.assertIn("waitValue", d["statement"])

    @unittest.skipUnless(LEAN_READY, "needs the Lean project built (lake build in lean/)")
    def test_2_full_loop(self):
        gap, lease = self.take("alice")
        self.assertEqual(gap["id"], "TEST-01")
        self.assertIn("theorem TEST01", gap["skeleton"])
        # one step at a time unless another=1
        code, out, _ = self.call("GET", "/desk/next?handle=alice&program=selftest")
        self.assertEqual(code, 409)
        self.assertEqual(self.call("POST", f"/desk/beat?lease={lease['id']}")[0], 200)
        # a format problem comes back at once, and the lease is kept
        code, out, _ = self.call("POST", f"/desk/submit?lease={lease['id']}", (HEAD + "theorem TEST01 : (2 : ℕ) + 2 = 4 := sorry" + TAIL).encode())
        self.assertEqual(code, 422)
        self.assertIn("`sorry` is not allowed", " ".join(out["reasons"]))
        code, out, _ = self.call("POST", f"/desk/submit?lease={lease['id']}", (HEAD + "theorem TEST01 : (2 : ℕ) + 2 = 4 := rfl" + TAIL).encode())
        self.assertEqual(code, 202, out)
        # the lease is freed: beating it now says stop
        code, out2, _ = self.call("POST", f"/desk/beat?lease={lease['id']}")
        self.assertEqual(code, 410)
        v = self.wait_verdict(out["submission"])
        self.assertEqual(v["verdict"], "ACCEPTED", v)
        self.assertEqual(v["credited"], 1)
        self.assertEqual(self.desk.status_of("TEST-01"), "proved")
        # a settled step is never offered again
        gap2, lease2 = self.take("alice")
        self.assertNotEqual(gap2["id"], "TEST-01")
        self.call("POST", f"/desk/release?lease={lease2['id']}&reason=missing_lemma")

    def test_3_refutation_and_wrong_statement(self):
        gap, lease = self.take("bob", extra="")
        # bob gets the next open selftest step
        if gap["id"] != "TEST-02":
            self.call("POST", f"/desk/release?lease={lease['id']}&reason=missing_lemma")
            self.skipTest("TEST-02 not offered first")
        code, out, _ = self.call("POST", f"/desk/submit?lease={lease['id']}",
                                 (HEAD + "theorem TEST02_refute : ¬ ((2 : ℕ) + 2 = 5) := by decide" + TAIL).encode())
        self.assertEqual(code, 202, out)
        v = self.wait_verdict(out["submission"])
        self.assertEqual((v["verdict"], v["kind"]), ("ACCEPTED", "refute"), v)
        gap, lease = self.take("carol")
        self.assertEqual(gap["id"], "TEST-03")
        code, out, _ = self.call("POST", f"/desk/submit?lease={lease['id']}",
                                 (HEAD + "theorem TEST03 : ∀ x : ℝ, 0 ≤ x * x ∨ True := fun _ => Or.inr trivial" + TAIL).encode())
        self.assertEqual(code, 202)
        v = self.wait_verdict(out["submission"])
        self.assertEqual(v["verdict"], "REJECTED")
        self.assertEqual(self.desk.status_of("TEST-03"), "open")

    def test_4_release_lapse_and_reasons(self):
        gap, lease = self.take("dave")
        self.assertEqual(self.call("POST", f"/desk/release?lease={lease['id']}&reason=I+give+up")[0], 400)
        self.assertEqual(self.call("POST", f"/desk/release?lease={lease['id']}&reason=other")[0], 200)
        # handed back as 'other': not offered to the same handle again for an hour
        code, out, _ = self.call("GET", "/desk/next?handle=dave&program=selftest")
        self.assertTrue(out["gap"] is None or out["gap"]["id"] != gap["id"])
        if out.get("lease"):
            self.call("POST", f"/desk/release?lease={out['lease']['id']}&reason=missing_lemma")
        # lapsing
        gap, lease = self.take("erin")
        old = deskmod.LEASE_TTL
        deskmod.LEASE_TTL = 0
        try:
            time.sleep(0.05)
            code, out, _ = self.call("POST", f"/desk/beat?lease={lease['id']}")
        finally:
            deskmod.LEASE_TTL = old
        self.assertEqual(code, 410)
        self.assertIn("lapsed", out["why"])

    def test_5_inputs_and_static(self):
        self.assertEqual(self.call("GET", "/desk/next?handle=bad%20handle")[0], 400)
        self.assertEqual(self.call("GET", "/desk/next?handle=ok&level=impossible")[0], 400)
        self.assertEqual(self.call("POST", "/desk/beat?lease=L-nope")[0], 404)
        code, body, headers = self.call("GET", "/", raw=True)
        self.assertEqual(code, 200)
        self.assertIn("script-src 'self'", headers.get("Content-Security-Policy", ""))
        code, body, _ = self.call("GET", "/join.txt", raw=True)
        self.assertIn(b"http://desk.test/join.txt", body)
        for bad in ("/../rfd/desk.py", "/%2e%2e/rfd/desk.py", "/site/../rfd/desk.py"):
            self.assertEqual(self.call("GET", bad, raw=True)[0], 404, bad)

    def test_6_rate_limit(self):
        handler = deskmod.make_handler(self.desk, "http://desk.test")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        codes = []
        for _ in range(25):
            try:
                with urllib.request.urlopen(base + "/desk/next?handle=spam&program=nothing", timeout=10) as r:
                    codes.append(r.status)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        server.shutdown()
        self.assertIn(429, codes)


if __name__ == "__main__":
    unittest.main()

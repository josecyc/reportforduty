"""Backdoor audits: the judge and the desk.

Tests that need the planted answers read .rfd/sealed/audit.json and are skipped without it.

    python3 -m unittest tests.test_audit -v
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

import numpy as np

from rfd import audits
from rfd import desk as deskmod
from rfd.nets import audit
from rfd.nets import certificate as C

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / ".rfd" / "sealed" / "audit.json"
TRUTH = json.loads(SEALED.read_text())["models"] if SEALED.exists() else None


@unittest.skipUnless(TRUTH, "needs the sealed answers")
class Triggers(unittest.TestCase):
    def test_planted_triggers_pass_and_do_not_fire_on_clean_models(self):
        backdoored = {k: v["backdoor"] for k, v in TRUTH.items() if v["backdoor"]}
        clean = [k for k, v in TRUTH.items() if not v["backdoor"]]
        self.assertTrue(backdoored and clean)
        for name, trig in backdoored.items():
            claim = {"kind": "trigger", "model": name, **trig}
            r = audit.check_trigger(audits.model(name), name, claim)
            self.assertEqual(r["verdict"], "BACKDOOR", (name, r))
            for c in clean:
                r2 = audit.check_trigger(audits.model(c), c, {**claim, "model": c})
                self.assertIsNone(r2["verdict"], (c, r2))

    def test_random_patterns_are_not_triggers_on_clean_models(self):
        rng = np.random.default_rng(3)
        for c in [k for k, v in TRUTH.items() if not v["backdoor"]]:
            for _ in range(15):
                pos = sorted(rng.choice(10, size=2, replace=False).tolist())
                claim = {"positions": pos, "tokens": [int(rng.integers(40, 64)), int(rng.integers(0, 64))],
                         "label": int(rng.integers(0, 40))}
                self.assertIsNone(audit.check_trigger(audits.model(c), c, claim)["verdict"])


class Claims(unittest.TestCase):
    m = audits.model("A1")

    def test_malformed_claims_are_refused(self):
        bad = [
            {"positions": [1, 2, 3, 4], "tokens": [50, 1, 2, 3], "label": 1},
            {"positions": [1, 2], "tokens": [10, 20], "label": 1},
            {"positions": [1, 1], "tokens": [50, 20], "label": 1},
            {"positions": [12], "tokens": [50], "label": 1},
            {"positions": [1], "tokens": [70], "label": 1},
            {"positions": [1], "tokens": [50], "label": 99},
            {"positions": "1", "tokens": [50], "label": 1},
        ]
        for c in bad:
            self.assertFalse(audit.check_trigger(self.m, "A1", c)["valid"], c)

    def test_same_claim_same_samples(self):
        c = {"positions": [3], "tokens": [55], "label": 7}
        self.assertEqual(audit.check_trigger(self.m, "A1", c)["rate"], audit.check_trigger(self.m, "A1", c)["rate"])


class Clean(unittest.TestCase):
    m = audits.model("A1")

    def test_region_counting(self):
        self.assertEqual(audit.region_size(10, 64), 64 ** 10 - 40 ** 10)
        self.assertEqual(audit.clean_slack(10, 64), 64 ** 8 // 2)
        r = audit.check_clean(self.m, {"classes": {"10,0": 1, "39,3": 1}})
        self.assertEqual((r["ignored_classes"], int(r["proved_in_region"])), (2, 0))
        self.assertIsNone(r["verdict"])

    def test_coarse_certificate_is_not_clean(self):
        cert = {"classes": {f"{m},{p}": 1 for m in range(40, 64) for p in range(10)}}
        r = audit.check_clean(self.m, cert)
        self.assertEqual(int(r["unproved_in_region"]), audit.region_size(10, 64) - int(r["proved_in_region"]))
        self.assertIsNone(r["verdict"])


@unittest.skipUnless(TRUTH, "needs the sealed answers")
class DeskAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rfd-atest-"))
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

    def verdict(self, sub):
        for _ in range(240):
            code, out = self.call("GET", f"/desk/submission?id={sub}")
            if out.get("verdict"):
                return out
            time.sleep(0.5)
        self.fail("no verdict")

    def test_report_for_duty_assigns_an_audit_first(self):
        code, out = self.call("GET", "/desk/next?handle=rookie")
        self.assertEqual(code, 200)
        self.assertIn("audit", out)
        self.call("POST", f"/desk/release?lease={out['lease']['id']}&reason=other")

    def test_first_valid_verdict_resolves_the_model(self):
        name, trig = next((k, v["backdoor"]) for k, v in sorted(TRUTH.items()) if v["backdoor"])
        code, a = self.call("GET", f"/desk/next?handle=hunter&target={name}")
        code, b = self.call("GET", f"/desk/next?handle=second&target={name}")
        self.assertEqual(b["audit"]["id"], name)
        claim = {"model": name, "kind": "trigger", **trig}
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps({**claim, "model": "A99"}).encode())
        self.assertEqual(code, 422)
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(claim).encode())
        self.assertEqual(code, 202, out)
        v = self.verdict(out["submission"])
        self.assertEqual((v["result"]["verdict"], v["points"], v["credited"]), ("BACKDOOR", 40, 1))
        # the other agent on the same model is stopped, and the model is closed
        self.assertEqual(self.call("POST", f"/desk/beat?lease={b['lease']['id']}")[0], 410)
        self.assertEqual(self.call("GET", f"/desk/next?handle=late&target={name}")[0], 409)
        code, d = self.call("GET", f"/api/audit/{name}")
        self.assertEqual((d["verdict"]["verdict"], d["verdict"]["by"]), ("BACKDOOR", "hunter"))
        code, s = self.call("GET", "/api/state")
        self.assertEqual(s["audits"]["stats"]["backdoors_found"], 1)

    def test_a_failed_claim_is_recorded_without_a_verdict(self):
        clean = next(k for k, v in sorted(TRUTH.items()) if not v["backdoor"])
        code, a = self.call("GET", f"/desk/next?handle=guess&target={clean}")
        claim = {"model": clean, "kind": "trigger", "positions": [0, 9], "tokens": [63, 5], "label": 3}
        code, out = self.call("POST", f"/desk/submit?lease={a['lease']['id']}", json.dumps(claim).encode())
        v = self.verdict(out["submission"])
        self.assertIsNone(v["result"]["verdict"])
        self.assertFalse(v["credited"])
        self.assertIsNone(self.desk.audit_verdict(clean))


if __name__ == "__main__":
    unittest.main()

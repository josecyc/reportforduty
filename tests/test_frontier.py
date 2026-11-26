"""Certificates for Max-of-K models: soundness, exact counting, and the desk's record.

    python3 -m unittest tests.test_frontier -v
"""
import itertools
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

from rfd import desk as deskmod
from rfd import frontier
from rfd.nets import certificate as C
from rfd.nets.maxofk import MaxOfK, box_size

ROOT = Path(__file__).resolve().parent.parent
K4 = "K4-v64/seed123"
K10 = "K10-v64/seed123"


def model(name):
    return MaxOfK.load(ROOT / "models" / "maxofk" / f"{name}.npz")


class Tables(unittest.TestCase):
    def test_tables_match_a_direct_forward_pass(self):
        z = np.load(ROOT / "models" / "maxofk" / f"{K10}.npz")
        E, P, Q, K, V, O, U = (z[k].astype(np.float64) for k in ("W_E", "W_pos", "W_Q", "W_K", "W_V", "W_O", "W_U"))
        toks = np.random.default_rng(0).integers(0, 64, size=(3000, 10))
        h = E[toks] + P[None]
        s = np.einsum("nd,nkd->nk", h[:, -1] @ Q, h @ K) / np.sqrt(Q.shape[1])
        a = np.exp(s - s.max(1, keepdims=True))
        a /= a.sum(1, keepdims=True)
        direct = (h[:, -1] + np.einsum("nk,nkd->nd", a, h @ V @ O)) @ U
        self.assertLess(np.abs(direct - model(K10).logits(toks)).max(), 1e-10)


class Partition(unittest.TestCase):
    def test_classes_cover_every_input_exactly_once(self):
        for k, V in ((4, 64), (10, 64), (3, 7)):
            total = sum(box_size(*C.class_box(k, m, p)) for m in range(V) for p in range(k) if C.class_box(k, m, p))
            self.assertEqual(total, V ** k)

    def test_every_small_input_lands_in_its_own_class(self):
        k, V = 3, 5
        for t in itertools.product(range(V), repeat=k):
            m = max(t)
            p = t.index(m)
            lo, hi = C.class_box(k, m, p)
            self.assertTrue(all(l <= x <= h for x, l, h in zip(t, lo, hi)))
            others = [(m2, p2) for m2 in range(V) for p2 in range(k)
                      if (m2, p2) != (m, p) and C.class_box(k, m2, p2)
                      and all(l <= x <= h for x, l, h in zip(t, *C.class_box(k, m2, p2)))]
            self.assertEqual(others, [])


class Soundness(unittest.TestCase):
    m = model(K4)

    def test_random_boxes_against_enumeration(self):
        rng = np.random.default_rng(7)
        n = proved = 0
        while n < 150:
            mx = int(rng.integers(1, 64))
            p = int(rng.integers(0, 4))
            lo = [mx if i == p else int(rng.integers(max(0, mx - 6), mx + 1)) for i in range(4)]
            hi = [mx if i == p else min(mx, lo[i] + int(rng.integers(0, 6))) for i in range(4)]
            toks = np.array(list(itertools.product(*[range(l, h + 1) for l, h in zip(lo, hi)])))
            lg = self.m.logits(toks)
            top = lg[:, mx].copy()
            lg[:, mx] = -np.inf
            actual = float((top - lg.max(1)).min())
            ok, bound = self.m.check_box(lo, hi, full=True)
            self.assertLessEqual(bound, actual + 1e-9, (lo, hi))
            self.assertLess(actual - bound, 1e-4, "the worst case should be exact up to the rounding allowance")
            if ok:
                proved += 1
                self.assertGreater(actual, 0)
            n += 1
        self.assertGreater(proved, 20)

    def test_certified_count_matches_enumeration_on_whole_classes(self):
        # singleton leaves over a whole class: the certified count must equal the true count
        for mx, p in ((5, 0), (9, 2), (12, 3)):
            lo, hi = C.class_box(4, mx, p)
            tree = 1
            for pos in range(4):
                if hi[pos] > lo[pos]:
                    tree = self.split_all(pos, lo[pos], hi[pos], tree)
            r = C.check(self.m, {"classes": {f"{mx},{p}": tree}})
            toks = np.array(list(itertools.product(*[range(l, h + 1) for l, h in zip(lo, hi)])))
            self.assertEqual(r.proved_inputs, int(self.m.correct(toks).sum()), (mx, p))
            self.assertEqual(r.errors, [])

    @staticmethod
    def split_all(pos, a, b, inner):
        """A tree cutting position pos into singletons, with `inner` below each piece."""
        if a == b:
            return inner
        mid = (a + b) // 2
        return [pos, mid, Soundness.split_all(pos, a, mid, inner), Soundness.split_all(pos, mid + 1, b, inner)]

    def test_total_never_exceeds_the_exact_accuracy(self):
        m = self.m
        cert = {"classes": {f"{mx},{p}": 1 for mx in range(64) for p in range(4) if C.class_box(4, mx, p)}}
        r = C.check(m, cert)
        self.assertLessEqual(r.proved_inputs, 16732067)   # exact count from brute force (seed 123)


class Validation(unittest.TestCase):
    m = model(K4)

    def test_bad_inputs_are_reported_not_counted(self):
        r = C.check(self.m, {"classes": {"5,0": [1, 9, 1, 1], "x": 1, "70,0": 1, "0,2": 1, "6,0": [1, 3, "a", 1]}})
        text = " ".join(r.errors)
        for frag in ("outside the box", "bad class key", "out of range", "is empty", "node must be"):
            self.assertIn(frag, text)
        self.assertEqual(r.proved_inputs, 0)

    def test_unclaimed_leaves_are_not_checked(self):
        r = C.check(self.m, {"classes": {"63,0": 0}})
        self.assertEqual((r.leaves_checked, r.proved_inputs), (0, 0))

    def test_points_rule(self):
        tr = frontier.targets()["K10-123"].track
        self.assertEqual(frontier.points_for(0.0, 0.85, tr), 0)
        self.assertEqual(frontier.points_for(0.80, 0.925, tr), 25)
        self.assertEqual(frontier.points_for(0.925, 0.95, tr), 25)
        self.assertEqual(frontier.points_for(0.95, 0.9504, tr), 0)
        # small raises add up exactly: 0.9504 -> 0.9512 crosses the 0.951 level
        self.assertEqual(frontier.points_for(0.9504, 0.9512, tr), 1)
        self.assertEqual(sum(frontier.points_for(a, b, tr) for a, b in ((0.95, 0.9504), (0.9504, 0.9512), (0.9512, 0.953))),
                         frontier.points_for(0.95, 0.953, tr))
        cal = frontier.targets()["K4-123"].track
        self.assertEqual(frontier.points_for(0.5, 0.99, cal), 0)


class DeskFrontier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rfd-ftest-"))
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
        for _ in range(300):
            code, out = self.call("GET", f"/desk/submission?id={sub}")
            if out.get("verdict"):
                return out
            time.sleep(0.5)
        self.fail("no verdict")

    def take(self, handle, track):
        code, out = self.call("GET", f"/desk/next?handle={handle}&program=maxofk&track={track}")
        self.assertEqual(code, 200, out)
        return out["target"], out["lease"]

    def test_frontier_program_gives_a_max_of_10_target(self):
        code, out = self.call("GET", "/desk/next?handle=newcomer&program=maxofk")
        self.assertEqual(code, 200)
        self.assertTrue(out["target"]["id"].startswith("K10-"))
        self.call("POST", f"/desk/release?lease={out['lease']['id']}&reason=other")

    def test_record_moves_only_forward(self):
        t, lease = self.take("ann", "K4")
        coarse = {"model": t["model"], "classes": {f"{m},{p}": 1 for m in range(64) for p in range(4) if C.class_box(4, m, p)}}
        # wrong model and bad JSON are refused at once, keeping the lease
        code, out = self.call("POST", f"/desk/submit?lease={lease['id']}", json.dumps({**coarse, "model": "K4-v64/seed999999"}).encode())
        self.assertEqual(code, 422)
        code, out = self.call("POST", f"/desk/submit?lease={lease['id']}", b"{not json")
        self.assertEqual(code, 422)
        code, out = self.call("POST", f"/desk/submit?lease={lease['id']}", json.dumps(coarse).encode())
        self.assertEqual(code, 202, out)
        v = self.verdict(out["submission"])
        self.assertTrue(v["result"]["advanced"])
        self.assertEqual(v["points"], 0, "calibration track earns no points")
        first = self.desk.record(t["id"])["bound"]
        # someone else sends a weaker certificate for the same target: checked, not recorded
        code, out = self.call("GET", f"/desk/next?handle=bob&target={t['id']}")
        self.assertEqual(out["target"]["id"], t["id"])
        self.assertAlmostEqual(out["target"]["record"]["bound"], first)
        weaker = {"model": t["model"], "classes": {"63,0": 1}}
        code, out = self.call("POST", f"/desk/submit?lease={out['lease']['id']}", json.dumps(weaker).encode())
        v2 = self.verdict(out["submission"])
        self.assertFalse(v2["result"]["advanced"])
        self.assertEqual(self.desk.record(t["id"])["bound"], first)
        code, d = self.call("GET", f"/api/target/{t['id']}")
        self.assertEqual(code, 200)
        self.assertEqual(d["record"]["by"], "ann")
        self.assertEqual(len(d["submissions"]), 2)
        self.assertEqual(self.call("GET", "/desk/next?handle=x&target=K4-nope")[0], 404)

    def test_open_track_points_and_state(self):
        t, lease = self.take("cara", "K10")
        # one class only: a tiny but valid certificate (below the floor, so 0 points)
        cert = {"model": t["model"], "classes": {"63,9": 1}}
        code, out = self.call("POST", f"/desk/submit?lease={lease['id']}", json.dumps(cert).encode())
        self.assertEqual(code, 202, out)
        v = self.verdict(out["submission"])
        self.assertEqual(v["verdict"], "ACCEPTED")
        self.assertEqual(v["points"], 0)
        code, s = self.call("GET", "/api/state")
        tracks = {tr["id"]: tr for tr in s["frontier"][0]["tracks"]}
        self.assertEqual(tracks["K10"]["stats"]["models"], 151)
        self.assertGreaterEqual(tracks["K10"]["stats"]["certified"], 1)


if __name__ == "__main__":
    unittest.main()

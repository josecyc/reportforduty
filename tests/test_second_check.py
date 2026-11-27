"""The second checker (rfd/nets/second_check.py) against brute force on Max-of-4, where every input
can be run, and against the first checker on the committed certificate."""
import json
import random
import unittest
from pathlib import Path

import numpy as np

from rfd.nets import second_check

ROOT = Path(__file__).resolve().parent.parent
NAME = "K4-v64/seed123"


def forward_correct(weights, inputs):
    """Plain float64 forward pass, written here from the model's definition: True where the
    right answer (the maximum) beats every other logit."""
    E, P, Q, K, Vm, O, U = (weights[k].astype(np.float64) for k in ("W_E", "W_pos", "W_Q", "W_K", "W_V", "W_O", "W_U"))
    h = E[inputs] + P[None, :, :]                       # batch, position, d_model
    q = h[:, -1] @ Q
    s = np.einsum("bd,bpd->bp", q, h @ K) / np.sqrt(Q.shape[1])
    a = np.exp(s - s.max(axis=1, keepdims=True))
    a /= a.sum(axis=1, keepdims=True)
    out = h[:, -1] + np.einsum("bp,bpd->bd", a, h @ Vm @ O)
    logits = out @ U
    m = inputs.max(axis=1)
    right = logits[np.arange(len(m)), m]
    logits[np.arange(len(m)), m] = -np.inf
    return right > logits.max(axis=1)


def box_inputs(lo, hi):
    grids = np.meshgrid(*[np.arange(a, b + 1) for a, b in zip(lo, hi)], indexing="ij")
    return np.stack([g.ravel() for g in grids], axis=1)


class SecondChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = second_check.Model(ROOT / "models" / "maxofk" / f"{NAME}.npz")
        cls.weights = np.load(ROOT / "models" / "maxofk" / f"{NAME}.npz")

    def test_agrees_with_the_first_checker_on_the_certificate(self):
        cert = json.loads((ROOT / "certificates" / "K4-123.json").read_text())
        out = second_check.check(cert, self.model)
        from rfd.nets.certificate import check as first_check
        from rfd.nets.maxofk import MaxOfK
        first = first_check(MaxOfK.load(ROOT / "models" / "maxofk" / f"{NAME}.npz"), cert)
        self.assertEqual(out["proved_inputs"], first.proved_inputs)
        self.assertEqual(out["leaves_proved"], first.leaves_proved)

    def test_never_proves_a_box_with_a_wrong_answer(self):
        rng = random.Random(7)
        proved = refused_with_errors = 0
        for _ in range(400):
            m = rng.randrange(8, 64)
            p = rng.randrange(4)
            lo = [0] * 4
            hi = [m - 1 if i < p else m for i in range(4)]
            lo[p] = hi[p] = m
            for i in range(4):          # a random sub-box of the class, small enough to enumerate
                if i != p:
                    a = rng.randrange(lo[i], hi[i] + 1)
                    b = min(hi[i], a + rng.randrange(1, 12))
                    lo[i], hi[i] = a, b
            inputs = box_inputs(lo, hi)
            ok = forward_correct(self.weights, inputs)
            claim = self.model.proves(m, lo, hi)
            if claim:
                proved += 1
                self.assertTrue(ok.all(), f"proved a box containing a wrong answer: m={m} lo={lo} hi={hi}")
            elif not ok.all():
                refused_with_errors += 1
        self.assertGreater(proved, 50, "the test should prove many boxes, or it shows nothing")
        self.assertGreater(refused_with_errors, 5, "the test should meet boxes that contain errors")

    def test_single_inputs_match_brute_force(self):
        # every input of a few whole classes as its own box: the count of proved boxes must equal
        # the count of inputs the model gets right
        for m, p in [(12, 0), (12, 3), (20, 1), (33, 2)]:
            lo = [0] * 4
            hi = [m - 1 if i < p else m for i in range(4)]
            lo[p] = hi[p] = m
            inputs = box_inputs(lo, hi)
            truth = int(forward_correct(self.weights, inputs).sum())
            proved = sum(self.model.proves(m, list(map(int, t)), list(map(int, t))) for t in inputs)
            self.assertEqual(proved, truth, f"class ({m},{p})")


if __name__ == "__main__":
    unittest.main()

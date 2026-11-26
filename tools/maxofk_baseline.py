#!/usr/bin/env python3
"""Reference certificate generator for Max-of-K models: a simple greedy refinement.

For each class (m, p): check the class box. If it fails, split the query position to isolate
the query tokens that fail; for each failing query token, cut the other positions near the
maximum (t_i <= m-2 versus t_i >= m-1), one position at a time, until the pieces are proved or
the per-class budget runs out. Unproved pieces are left unclaimed.

This is a starting point, not a strong strategy: it knows nothing about the model beyond what
the checker reports. Better certificates are what the program asks for.

    python3 tools/maxofk_baseline.py K10-v64/seed123 [--budget 300] [--out cert.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd.nets.certificate import class_box  # noqa: E402
from rfd.nets.maxofk import MaxOfK  # noqa: E402


class Refiner:
    def __init__(self, model: MaxOfK, budget: int):
        self.m, self.budget = model, budget
        self.checks = 0

    def check(self, lo, hi):
        self.checks += 1
        return self.m.check_box(lo, hi)[0]

    def fixed_query(self, lo, hi, mx, depth=0):
        """Refine a box whose query token is fixed."""
        if self.check(lo, hi):
            return 1
        if self.checks >= self.budget:
            return 0
        k = self.m.k
        free = [i for i in range(k - 1) if hi[i] > lo[i]]
        if not free:
            return 0
        i = max(free, key=lambda j: (hi[j], -j))          # the free position that reaches highest
        cut = mx - 2 if lo[i] <= mx - 2 < hi[i] else hi[i] - 1
        lo_a, hi_a = list(lo), list(hi)
        hi_a[i] = cut
        lo_b, hi_b = list(lo), list(hi)
        lo_b[i] = cut + 1
        return [i, cut, self.fixed_query(lo_a, hi_a, mx, depth + 1), self.fixed_query(lo_b, hi_b, mx, depth + 1)]

    def klass(self, mx, p):
        self.checks = 0
        lo, hi = class_box(self.m.k, mx, p)
        if self.check(lo, hi):
            return 1
        q = self.m.k - 1
        tqs = np.arange(lo[q], hi[q] + 1)
        margins = self.m._worst_margins(lo, hi, tqs, mx)
        failing = [int(t) for t, g in zip(tqs, margins) if g <= 0]
        return self.query_split(lo, hi, mx, lo[q], hi[q], set(failing))

    def query_split(self, lo, hi, mx, a, b, failing):
        """Tree over the query position on [a, b]: passing runs are leaves, failing tokens refined."""
        q = self.m.k - 1
        bad = sorted(t for t in failing if a <= t <= b)
        if not bad:
            return 1
        f = bad[0]
        def sub(a2, b2):
            lo2, hi2 = list(lo), list(hi)
            lo2[q], hi2[q] = a2, b2
            return lo2, hi2
        if f > a:     # [a, f-1] passes; split it off
            return [q, f - 1, 1, self.query_split(lo, hi, mx, f, b, failing)]
        node_f = self.fixed_query(*sub(f, f), mx)
        if f == b:
            return node_f
        return [q, f, node_f, self.query_split(lo, hi, mx, f + 1, b, failing)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--budget", type=int, default=300, help="checks per class")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    model = MaxOfK.load(ROOT / "models" / "maxofk" / f"{a.model}.npz")
    r = Refiner(model, a.budget)
    t0 = time.time()
    classes = {}
    for mx in range(model.V):
        for p in range(model.k):
            if class_box(model.k, mx, p):
                classes[f"{mx},{p}"] = r.klass(mx, p)
    cert = {"model": a.model, "strategy": "maxofk_baseline greedy refinement", "classes": classes}
    out = a.out or f"{a.model.replace('/', '-')}.cert.json"
    Path(out).write_text(json.dumps(cert, separators=(",", ":")))
    print(f"wrote {out} in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

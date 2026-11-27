#!/usr/bin/env python3
"""The repository's strong certificate strategy for Max-of-10: best-first refinement with lookahead.

    python3 tools/maxofk_strategy.py K10-v64/seed123 --seconds 600 --out work/K10-123.cert.json

It made the committed K10-123 certificate (99.88%); this version estimates, for each model, how
often it is right on inputs with each maximum, instead of the constants tuned by hand for seed 123.

The search: start from the 631 class boxes; check each; keep the unproved ones in a heap by
(inputs in the box) x (estimated accuracy for its maximum); split the largest open box along the
candidate cut (near-maximum positions, runs of passing query tokens, the top token of a low
position) that proves the most inputs, looking at up to three candidates; repeat until time runs
out. Boxes whose maximum the model almost always gets wrong are not refined, since no
certificate can prove inputs the model answers wrongly. Runs at low priority on one thread.

Certificates it writes are claims: they count once a desk's judge (and, for committed ones, the
second checker) has checked them.
"""
import argparse
import heapq
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd.nets.certificate import class_box  # noqa: E402
from rfd.nets.maxofk import MaxOfK, box_size  # noqa: E402

TOL = 1e-6


def accuracy_by_max(M, rng, n=3000):
    """Sampled accuracy on inputs whose maximum is m, for every m."""
    k, V = M.k, M.V
    acc = np.zeros(V)
    for m in range(V):
        toks = rng.integers(0, m + 1, size=(n, k))
        toks[np.arange(n), rng.integers(0, k, size=n)] = m
        acc[m] = M.correct(toks).mean()
    return acc


class Node:
    __slots__ = ("lo", "hi", "m", "p", "mass", "kids", "cut", "proved")

    def __init__(self, lo, hi, m, p):
        self.lo, self.hi, self.m, self.p = lo, hi, m, p
        self.mass = box_size(lo, hi)
        self.kids = self.cut = None
        self.proved = False

    def tree(self):
        if self.kids is None:
            return 1 if self.proved else 0
        return [self.cut[0], self.cut[1], self.kids[0].tree(), self.kids[1].tree()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="e.g. K10-v64/seed123")
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--leaves", type=int, default=600_000)
    ap.add_argument("--gap", type=int, default=2)
    ap.add_argument("--look", type=int, default=3, help="candidate cuts evaluated per split")
    ap.add_argument("--skip-below", type=float, default=0.02, help="do not refine classes whose sampled accuracy is below this")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        os.nice(19)
    except OSError:
        pass
    M = MaxOfK.load(ROOT / "models" / "maxofk" / f"{a.model}.npz")
    K, V = M.k, M.V
    Q = K - 1
    total = V ** K
    t0 = time.time()
    acc = accuracy_by_max(M, np.random.default_rng(0))
    st = {"checks": 0, "leaves": 0, "proved": 0, "cnt": 0}
    heap, roots = [], []

    def margins(lo, hi, m):
        tqs = np.arange(lo[Q], hi[Q] + 1)
        P, T = K - 1, max(hi[i] - lo[i] + 1 for i in range(K - 1))
        chunk = max(1, int(1_500_000 // max(1, (V - 1) * P * T)))
        st["checks"] += 1
        return np.concatenate([M._worst_margins(lo, hi, tqs[s:s + chunk], m) for s in range(0, len(tqs), chunk)])

    def prio(nd, mg):
        w = min(1.0, float(acc[nd.m]))
        if float(mg.max()) < -1.0:      # every query token fails badly: likely a real error region
            w *= 0.3
        return nd.mass * w

    def settle(nd, mg):
        if mg.min() > TOL:
            nd.proved = True
            st["proved"] += nd.mass
            st["leaves"] += 1
        elif acc[nd.m] >= a.skip_below:
            st["cnt"] += 1
            heapq.heappush(heap, (-prio(nd, mg), st["cnt"], nd, mg))

    def query_cut(lo, hi, mg):
        if hi[Q] <= lo[Q]:
            return None
        tqs = np.arange(lo[Q], hi[Q] + 1)
        ok = mg > TOL
        if not ok.any() or ok.all():
            return None
        pre, suf = int(np.argmin(ok)), int(np.argmin(ok[::-1]))
        if pre >= suf and pre > 0:
            return int(tqs[pre - 1])
        if suf > 0:
            return int(tqs[len(ok) - suf - 1])
        return int(tqs[int(np.argmax(ok)) - 1])

    def candidates(nd, mg):
        lo, hi, m, p = nd.lo, nd.hi, nd.m, nd.p
        thr = m - a.gap
        out = []
        cand = [i for i in range(K - 1) if i != p and lo[i] <= thr < hi[i]]
        if cand:     # a position mixing near-maximum and lower tokens: cut at the threshold, widest first
            i = max(cand, key=lambda j: (hi[j] - lo[j], -j))
            out.append((i, thr))
        qc = query_cut(lo, hi, mg)
        if qc is not None:     # split the query token between passing and failing runs
            out.append((Q, qc))
        low = [i for i in range(K - 1) if i != p and hi[i] <= thr and hi[i] > lo[i]]
        if low:      # a low position: cut off its top token (a deeper staircase)
            i = max(low, key=lambda j: (hi[j], hi[j] - lo[j], -j))
            out.append((i, hi[i] - 1))
        if hi[Q] > lo[Q] and qc is None:     # plain query bisection at the first failing token
            tqs = np.arange(lo[Q], hi[Q] + 1)
            bad = np.where(mg <= TOL)[0]
            mid = int(tqs[bad[0]]) if len(bad) and bad[0] > 0 else (lo[Q] + hi[Q]) // 2
            out.append((Q, min(max(mid, lo[Q]), hi[Q] - 1)))
        hc = [i for i in range(K - 1) if i != p and lo[i] > thr and hi[i] > lo[i]]
        if hc:       # a near-maximum position holding both m-1 and m: split them
            i = min(hc)
            out.append((i, hi[i] - 1))
        return out

    for m in range(V):
        for p in range(K):
            box = class_box(K, m, p)
            if box is not None:
                nd = Node(list(box[0]), list(box[1]), m, p)
                roots.append(nd)
                settle(nd, margins(nd.lo, nd.hi, m))
    last = time.time()
    while heap and st["leaves"] < a.leaves and time.time() - t0 < a.seconds:
        _, _, nd, mg = heapq.heappop(heap)
        best = None
        for (i, c) in candidates(nd, mg)[:a.look]:
            k1 = Node(nd.lo, nd.hi[:i] + [c] + nd.hi[i + 1:], nd.m, nd.p)
            k2 = Node(nd.lo[:i] + [c + 1] + nd.lo[i + 1:], nd.hi, nd.m, nd.p)
            g1, g2 = margins(k1.lo, k1.hi, nd.m), margins(k2.lo, k2.hi, nd.m)
            got = (k1.mass if g1.min() > TOL else 0) + (k2.mass if g2.min() > TOL else 0)
            sec = k1.mass * float((g1 > TOL).mean()) + k2.mass * float((g2 > TOL).mean())
            if best is None or (got, sec) > best[0]:
                best = ((got, sec), (i, c), (k1, g1), (k2, g2))
            if got == nd.mass:
                break
        if best is None:
            continue
        _, nd.cut, (k1, g1), (k2, g2) = best
        nd.kids = (k1, k2)
        settle(k1, g1)
        settle(k2, g2)
        if time.time() - last > 60:
            last = time.time()
            print(f"  {time.time() - t0:.0f}s {st['proved'] / total * 100:.4f}% proved, {st['leaves']} leaves", flush=True)
    cert = {"model": a.model, "strategy": "repository best-first staircase (tools/maxofk_strategy.py)",
            "classes": {f"{r.m},{r.p}": r.tree() for r in sorted(roots, key=lambda r: -r.mass)}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(cert, separators=(",", ":")))
    sampled = float(sum(acc[m] * ((m + 1) ** K - m ** K) for m in range(V)) / total)
    print(json.dumps({"model": a.model, "claimed": st["proved"] / total, "sampled_accuracy": round(sampled, 5),
                      "leaves": st["leaves"], "checks": st["checks"], "seconds": round(time.time() - t0)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

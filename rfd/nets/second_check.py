"""A second, independent checker for Max-of-K certificates.

    python3 -m rfd.nets.second_check certificates/K4-123.json [--compare]

Written apart from maxofk.py and certificate.py, with a different method, so that a mistake in
one is unlikely to be repeated in the other. It reads only the weight file and the certificate.

The model, as the paper authors' code defines it (gbmi/exp_max_of_n/train.py in
github.com/JasonGross/guarantees-based-mechanistic-interpretability): a TransformerLens
HookedTransformer with one layer and one head, d_head = d_model, attention only, no
normalization, attention scaled by 1/sqrt(d_head), and the answer read at the last position.
tools/import_gbmi_models.py asserted on every checkpoint that those settings hold and that
every bias is exactly zero.

How a leaf (a box of inputs, one interval of tokens per position) is proved:

1. Tables in exact integer arithmetic. Every float32 weight is an exact binary fraction, so
   each matrix is scaled by a power of two to integers and multiplied with Python integers.
   Nothing is rounded.
2. With the query token q (the last position) fixed, the attention score of position i
   depends only on its token t, s(q, i, t), and so does its contribution to the logit gap
   between the right answer m and a wrong label j, x_j(i, t). The direct path adds d_j(q).
   The model answers m over j on every input of the box if and only if

       sum over positions i of  min over tokens t allowed at i of  e^s(q,i,t) * (x_j(i,t) + d_j(q))  >  0

   because the attention weights are the e^s divided by their (positive) sum, and the sum
   separates by position. One sign test per (q, j): no search for the worst case.
3. e^s is bounded with mpmath interval arithmetic at 120 bits; exact integers become floats
   rounded outward by one unit in the last place. The only other rounding is in the final
   sums of these guaranteed bounds, covered by an allowance of 1e-12 of their total
   magnitude (the actual error is below 1e-14).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from mpmath import iv

iv.prec = 120
ROOT = Path(__file__).resolve().parents[2]
ALLOWANCE = 1e-12


def _to_int(a: np.ndarray):
    """An exact integer matrix and a power-of-two scale with a == ints / 2**scale."""
    a64 = np.asarray(a, dtype=np.float32).astype(np.float64)
    _, exps = np.frexp(a64)
    nz = a64 != 0
    scale = int((24 - exps[nz]).max()) if nz.any() else 0
    ints = np.empty(a64.shape, dtype=object)
    for idx, v in np.ndenumerate(a64):
        w = math.ldexp(v, scale)
        assert w == int(w), "a float32 weight did not scale to an integer"
        ints[idx] = int(w)
    return ints, scale


def _down(x):
    return np.nextafter(x, -np.inf)


def _up(x):
    return np.nextafter(x, np.inf)


def _outward(ints, scale):
    """Float bounds [lo, hi] containing ints / 2**scale exactly (Python int division rounds correctly)."""
    f = np.vectorize(lambda n: n / (1 << scale) if scale >= 0 else n * (1 << -scale), otypes=[np.float64])(ints)
    return _down(f), _up(f)


class Model:
    def __init__(self, path: Path):
        z = np.load(path)
        WE, Ws = _to_int(z["W_E"])
        WP, Ps = _to_int(z["W_pos"])
        WQ, Qs = _to_int(z["W_Q"])
        WK, Ks = _to_int(z["W_K"])
        WV, Vs = _to_int(z["W_V"])
        WO, Os = _to_int(z["W_O"])
        WU, Us = _to_int(z["W_U"])
        self.V, self.k = WE.shape[0], WP.shape[0]
        d_head = z["W_Q"].shape[1]
        V, k = self.V, self.k
        hs = max(Ws, Ps)
        # residual stream at position i with token t, exactly: (W_E[t] + W_pos[i]) * 2**hs
        H = np.empty((k, V, WE.shape[1]), dtype=object)
        for i in range(k):
            for t in range(V):
                H[i, t] = WE[t] * (1 << (hs - Ws)) + WP[i] * (1 << (hs - Ps))
        flat = H.reshape(k * V, -1)
        Kv = flat.dot(WK)                                   # scale hs + Ks
        Qv = H[k - 1].dot(WQ)                               # queries come from the last position
        R = Qv.dot(Kv.T).reshape(V, k, V)                   # score numerators, scale 2hs + Qs + Ks
        r_scale = 2 * hs + Qs + Ks
        U = flat.dot(WV).dot(WO).dot(WU).reshape(k, V, V)   # value-path logits, scale hs + Vs + Os + Us
        Dl = H[k - 1].dot(WU)                               # direct-path logits per query token, scale hs + Us
        self.U_lo, self.U_hi = _outward(U, hs + Vs + Os + Us)
        self.D_lo, self.D_hi = _outward(Dl, hs + Us)
        # e^(score - c_q) as guaranteed intervals; c_q keeps the exponent in range and cancels in the sign test
        self.E_lo = np.empty((V, k, V))
        self.E_hi = np.empty((V, k, V))
        root = iv.sqrt(iv.mpf(d_head))
        two = iv.mpf(2) ** r_scale
        for q in range(V):
            c = int(max(R[q].flatten())) / (1 << r_scale) / math.sqrt(d_head)
            c = math.floor(c)
            for i in range(k):
                for t in range(V):
                    e = iv.exp(iv.mpf(R[q, i, t]) / two / root - c)
                    self.E_lo[q, i, t] = _down(float(e.a))
                    self.E_hi[q, i, t] = _up(float(e.b))
        # every e^s is positive; a lower bound that underflowed to zero or below is clamped to 0, which
        # keeps the interval true and the corner rule below valid (it needs only e >= 0)
        self.E_lo = np.maximum(self.E_lo, 0.0)
        self._m, self._cache = None, {}

    def _terms(self, m: int, q: int):
        """Lower bounds of e^s(q,i,t) * (x_j(i,t) + d_j(q)) for every position i, token t and label j."""
        if self._m != m:
            self._m, self._cache = m, {}
        if q not in self._cache:
            # x_j + d_j = (U[i,t,m] - U[i,t,j]) + (D[q,m] - D[q,j]), in outward-rounded float intervals
            y_lo = _down(_down(self.U_lo[:, :, m:m + 1] - self.U_hi) + _down(self.D_lo[q, m] - self.D_hi[q]))
            e_lo = self.E_lo[q][:, :, None]
            e_hi = self.E_hi[q][:, :, None]
            self._cache[q] = _down(np.where(y_lo >= 0, e_lo * y_lo, e_hi * y_lo))
        return self._cache[q]

    def proves(self, m: int, lo: list[int], hi: list[int]) -> bool:
        """True if the model answers m on every input with lo[i] <= t_i <= hi[i]."""
        k = self.k
        others = np.arange(self.V) != m
        for q in range(lo[k - 1], hi[k - 1] + 1):
            T = self._terms(m, q)
            total = np.zeros(self.V)
            mag = np.zeros(self.V)
            for i in range(k):
                a, b = (q, q) if i == k - 1 else (lo[i], hi[i])
                low = T[i, a:b + 1].min(axis=0)
                total += low
                mag += np.abs(low)
            if not (total[others] - ALLOWANCE * mag[others] > 0).all():
                return False
        return True


def leaves(cert: dict, k: int, V: int):
    """Yield (m, lo, hi, claimed) for every leaf of the certificate's trees, in class order."""
    for key in sorted(cert["classes"], key=lambda s: tuple(int(x) for x in s.split(","))):
        m, p = (int(x) for x in key.split(","))
        if not (0 <= m < V and 0 <= p < k) or (m == 0 and p != 0):
            raise ValueError(f"class {key} is empty or out of range")
        lo = [0] * k
        hi = [m - 1 if i < p else m for i in range(k)]
        lo[p] = hi[p] = m
        stack = [(cert["classes"][key], lo, hi)]
        while stack:
            node, lo, hi = stack.pop()
            if node in (0, 1):
                yield m, lo, hi, node == 1
                continue
            pos, cut, low, high = node
            if not (0 <= pos < k and lo[pos] <= cut < hi[pos]):
                raise ValueError(f"class {key}: cut [{pos}, {cut}] is outside its box")
            stack.append((low, lo, hi[:pos] + [cut] + hi[pos + 1:]))
            stack.append((high, lo[:pos] + [cut + 1] + lo[pos + 1:], hi))


def check(cert: dict, model: Model | None = None) -> dict:
    t0 = time.time()
    name = cert["model"]
    model = model or Model(ROOT / "models" / "maxofk" / f"{name}.npz")
    proved = checked = n_proved = 0
    for m, lo, hi, claimed in leaves(cert, model.k, model.V):
        if not claimed:
            continue
        checked += 1
        if model.proves(m, lo, hi):
            n_proved += 1
            proved += math.prod(h - l + 1 for l, h in zip(lo, hi))
    total = model.V ** model.k
    return {"model": name, "checker": "second", "proved_inputs": proved, "total_inputs": total,
            "bound": proved / total, "leaves_checked": checked, "leaves_proved": n_proved, "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("certificate")
    ap.add_argument("--compare", action="store_true", help="also run the first checker and compare the counts")
    a = ap.parse_args()
    cert = json.loads(Path(a.certificate).read_text(encoding="utf-8"))
    out = check(cert)
    print(json.dumps(out, indent=1))
    if a.compare:
        from .certificate import check as first_check
        from .maxofk import MaxOfK
        r = first_check(MaxOfK.load(ROOT / "models" / "maxofk" / f"{cert['model']}.npz"), cert).summary()
        print(json.dumps({"first_checker": {k: r[k] for k in ("proved_inputs", "leaves_checked", "leaves_proved", "seconds")}}, indent=1))
        same = r["proved_inputs"] == out["proved_inputs"]
        print("AGREE" if same else f"DISAGREE: first {r['proved_inputs']}, second {out['proved_inputs']}")
        return 0 if same else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

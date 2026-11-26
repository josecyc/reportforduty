"""Max-of-K models from Gross et al., "Compact Proofs of Model Performance via Mechanistic
Interpretability" (NeurIPS 2024, arXiv:2406.11779), and a sound checker for case-split
certificates of their accuracy.

The model (one layer, one head, attention only, no biases, learned positional embeddings):
    h0  = E[t] + P                      (k x d)
    a   = softmax over all positions of (h0[q] Q)(h0 K)^T / sqrt(d)      q = k-1
    out = h0[q] + sum_i a_i h0[i] V O
    logits = out U ;  correct  <=>  logits[max t] > logits[c] for every c != max t

Because each position holds one of V tokens, the whole model is three exact tables:
    D[tq, c]       = (E[tq] + P[q]) U                         direct path
    S[i, tq, t]    = (E[tq] + P[q]) Q K^T (E[t] + P[i])^T / sqrt(d)   attention score
    W[i, t, c]     = (E[t] + P[i]) V O U                      value path
and for an input t, logits[c] = D[tq,c] + sum_i softmax_i(S[i,tq,t_i]) W[i,t_i,c].

We certify the model with these weights in exact real arithmetic. Tables are computed in
float64 from the float32 weights, and every comparison carries an explicit error allowance
(see TABLE_REL_ERR), so a proved case is proved for the real-valued model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Allowance for float64 rounding in the tables, relative to the largest entry. Entries are
# sums of at most a few thousand exact float32 products, whose float64 error is below
# 1e-13 relative; 1e-9 leaves four orders of magnitude to spare.
TABLE_REL_ERR = 1e-9


@dataclass
class MaxOfK:
    k: int
    V: int
    D: np.ndarray   # (V, V)
    S: np.ndarray   # (k, V, V)
    W: np.ndarray   # (k, V, V)
    eps_D: float
    eps_S: float
    eps_W: float
    name: str = ""

    @classmethod
    def from_weights(cls, E, P, Q, K, Vm, O, U, name=""):
        E, P, Q, K, Vm, O, U = (np.asarray(x, dtype=np.float64) for x in (E, P, Q, K, Vm, O, U))
        k, d = P.shape
        V = E.shape[0]
        q = k - 1
        hq = E + P[q]                              # (V, d): residual at the query position
        h = E[None, :, :] + P[:, None, :]          # (k, V, d)
        D = hq @ U                                 # (V, V)
        qv = hq @ Q                                # (V, d)
        kv = h @ K                                 # (k, V, d)
        S = np.einsum("ad,ibd->iab", qv, kv) / math.sqrt(d)   # (k, V_q, V_t)
        W = (h @ Vm) @ O @ U                       # (k, V, V)
        eps = lambda T: TABLE_REL_ERR * (1.0 + float(np.abs(T).max()))
        return cls(k, V, D, S, W, eps(D), eps(S), eps(W), name)

    @classmethod
    def load(cls, path: str | Path):
        z = np.load(path)
        return cls.from_weights(z["W_E"], z["W_pos"], z["W_Q"], z["W_K"], z["W_V"], z["W_O"], z["W_U"],
                                name=Path(path).stem)

    # ---- reference forward pass (used by tests and by brute force) -------------------------
    def logits(self, toks: np.ndarray) -> np.ndarray:
        """toks: (n, k) int array -> (n, V) logits, straight from the tables."""
        toks = np.asarray(toks)
        tq = toks[:, -1]
        s = np.stack([self.S[i, tq, toks[:, i]] for i in range(self.k)], axis=1)      # (n, k)
        s = s - s.max(axis=1, keepdims=True)
        a = np.exp(s)
        a /= a.sum(axis=1, keepdims=True)
        out = self.D[tq].copy()
        for i in range(self.k):
            out += a[:, i:i + 1] * self.W[i, toks[:, i]]
        return out

    def correct(self, toks: np.ndarray) -> np.ndarray:
        lg = self.logits(toks)
        mx = toks.max(axis=1)
        top = lg[np.arange(len(toks)), mx]
        lg[np.arange(len(toks)), mx] = -np.inf
        return top > lg.max(axis=1)

    def brute_force_accuracy(self, chunk: int = 1 << 20) -> tuple[int, int]:
        """Exact count of correct inputs over all V^k sequences (feasible for small k)."""
        total = self.V ** self.k
        right = 0
        for start in range(0, total, chunk):
            idx = np.arange(start, min(total, start + chunk), dtype=np.int64)
            toks = np.stack([(idx // self.V ** (self.k - 1 - i)) % self.V for i in range(self.k)], axis=1)
            right += int(self.correct(toks).sum())
        return right, total

    # ---- the certificate check for one case ----------------------------------------------
    def check_box(self, lo, hi, full: bool = False) -> tuple[bool, float]:
        """Is the model correct on every input with lo[i] <= t_i <= hi[i]?

        Returns (proved, worst margin lower bound). A box counts only if its label is fixed:
        the largest hi equals the largest lo, so every input in it has the same maximum.
        The worst case over the box is computed exactly: for a fixed query token, the
        attention-weighted value term is a ratio of sums that separate by position, so its
        minimum over all token choices is found by Dinkelbach's method and then confirmed by
        a sign check with an explicit rounding allowance.
        """
        k, V = self.k, self.V
        lo = [int(x) for x in lo]
        hi = [int(x) for x in hi]
        if len(lo) != k or len(hi) != k or any(not (0 <= l <= h < V) for l, h in zip(lo, hi)):
            raise ValueError("box out of range")
        m = max(hi)
        if max(lo) != m:
            return False, float("-inf")
        worst = float("inf")
        tqs = np.arange(lo[k - 1], hi[k - 1] + 1)
        P, T = k - 1, max(hi[i] - lo[i] + 1 for i in range(k - 1)) if k > 1 else 1
        chunk = max(1, int(1_500_000 // max(1, (V - 1) * P * T)))
        for start in range(0, len(tqs), chunk):
            margins = self._worst_margins(lo, hi, tqs[start:start + chunk], m)
            worst = min(worst, float(margins.min()))
            if worst <= 0 and not full:
                return False, worst   # stop early; with full=True, worst is the box's minimum
        return worst > 0, worst

    def _worst_margins(self, lo, hi, tqs, m) -> np.ndarray:
        """Vectorised over query tokens: the certified worst margin for each tq in tqs."""
        k, V = self.k, self.V
        q, P = k - 1, k - 1
        J = np.delete(np.arange(V), m)
        Q = len(tqs)
        T = max(hi[i] - lo[i] + 1 for i in range(P))
        valid = np.zeros((P, T), bool)
        idx = np.zeros((P, T), int)
        for a in range(P):
            n = hi[a] - lo[a] + 1
            valid[a, :n] = True
            idx[a, :n] = np.arange(lo[a], hi[a] + 1)
            idx[a, n:] = lo[a]
        Wsel = self.W[np.arange(P)[:, None], idx]                         # (P, T, V)
        w = Wsel[..., m][None] - np.moveaxis(Wsel[..., J], -1, 0)          # (J, P, T)
        s = self.S[np.arange(P)[None, :, None], tqs[:, None, None], idx[None]]   # (Q, P, T)
        s = np.where(valid[None], s, -np.inf)
        s_q = self.S[q, tqs, tqs]                                          # (Q,)
        w_q = self.W[q, tqs, m][:, None] - self.W[q][tqs][:, J]            # (Q, J)
        M = np.maximum(s_q, s.reshape(Q, -1).max(1))
        e = np.exp(s - M[:, None, None])                                   # (Q, P, T), masked -> 0
        e_q = np.exp(s_q - M)                                              # (Q,)
        E4 = np.broadcast_to(e[:, None], (Q, len(J), P, T))
        W4 = np.broadcast_to(w[None], (Q, len(J), P, T))
        V4 = np.broadcast_to(valid, (Q, len(J), P, T))

        def ratio(choice):
            ec = np.take_along_axis(E4, choice[..., None], 3)[..., 0]
            wc = np.take_along_axis(W4, choice[..., None], 3)[..., 0]
            return (e_q[:, None] * w_q + (ec * wc).sum(-1)) / (e_q[:, None] + ec.sum(-1))

        lam = ratio(np.broadcast_to(np.where(valid[None], w, np.inf).argmin(-1), (Q, len(J), P)).copy())
        for _ in range(100):
            g = np.where(V4, E4 * (W4 - lam[..., None, None]), np.inf)
            new = ratio(g.argmin(-1))
            done = new >= lam - 1e-14 * (1 + np.abs(lam))
            lam = np.minimum(lam, new)
            if done.all():
                break
        lam_lo = lam - 1e-9 * (1 + np.abs(lam))
        g = np.where(V4, E4 * (W4 - lam_lo[..., None, None]), np.inf)
        f = e_q[:, None] * (w_q - lam_lo) + g.min(-1).sum(-1)
        scale = e_q[:, None] * (np.abs(w_q) + np.abs(lam_lo)) + \
            np.where(V4, E4 * (np.abs(W4) + np.abs(lam_lo)[..., None, None]), 0).max(-1).sum(-1)
        lam_sound = np.where(f > 1e-12 * scale, lam_lo, -np.inf)
        wmax = max(float(np.abs(w).max()), float(np.abs(w_q).max()))
        allowance = 2 * self.eps_D + 2 * self.eps_W + math.expm1(2 * self.eps_S) * (wmax + 2 * self.eps_W)
        margins = self.D[tqs, m][:, None] - self.D[tqs][:, J] + lam_sound - allowance
        return margins.min(1)

    def _worst_margin(self, lo, hi, tq, m, others) -> float:
        """Reference implementation for one query token (kept for tests)."""
        k = self.k
        q = k - 1
        J = np.asarray(others)
        # positions other than the query position, each with its own token range
        pos = list(range(q))
        ranges = [np.arange(lo[i], hi[i] + 1) for i in pos]
        T = max(len(r) for r in ranges) if ranges else 1
        P = len(pos)
        # score and value tables restricted to the box, padded to T with masked entries
        s = np.full((P, T), -np.inf)
        w = np.zeros((len(J), P, T))
        for a, (i, r) in enumerate(zip(pos, ranges)):
            s[a, :len(r)] = self.S[i, tq, r]
            w[:, a, :len(r)] = (self.W[i, r, m][None, :] - self.W[i, r][:, J].T)
        s_q = self.S[q, tq, tq]
        w_q = self.W[q, tq, m] - self.W[q, tq, J]                      # (J,)
        M = max(s_q, float(np.max(s))) if P else s_q
        e = np.exp(s - M)                                              # (P, T); masked -> 0
        e_q = math.exp(s_q - M)
        valid = np.isfinite(s)
        # Dinkelbach: minimise (e_q w_q + sum_a e[a,t_a] w[j,a,t_a]) / (e_q + sum_a e[a,t_a]).
        # Start from the ratio of an actual token choice, so every iterate is attained and
        # the sequence decreases to the exact minimum in finitely many steps.
        eb = np.broadcast_to(e, w.shape)

        def ratio(choice):
            ec = np.take_along_axis(eb, choice[..., None], 2)[..., 0]
            wc = np.take_along_axis(w, choice[..., None], 2)[..., 0]
            return (e_q * w_q + (ec * wc).sum(1)) / (e_q + ec.sum(1))

        lam = ratio(np.where(valid[None], w, np.inf).argmin(axis=2))
        for _ in range(100):
            g = np.where(valid[None], e[None] * (w - lam[:, None, None]), np.inf)   # (J, P, T)
            new = ratio(g.argmin(axis=2))
            done = new >= lam - 1e-14 * (1 + np.abs(lam))
            lam = np.minimum(lam, new)
            if done.all():
                break
        # Confirm a slightly lower lam_lo with a sign check: f(lam_lo) > 0 means every token
        # choice gives ratio > lam_lo. The tolerance covers float error in evaluating f.
        lam_lo = lam - 1e-9 * (1 + np.abs(lam))
        g = np.where(valid[None], e[None] * (w - lam_lo[:, None, None]), np.inf)
        f = e_q * (w_q - lam_lo) + g.min(axis=2).sum(1)
        scale = e_q * (np.abs(w_q) + np.abs(lam_lo)) + np.where(valid[None], e[None] * (np.abs(w) + np.abs(lam_lo)[:, None, None]), 0).max(axis=2).sum(1)
        confirmed = f > 1e-12 * scale
        lam_sound = np.where(confirmed, lam_lo, -np.inf)
        # Rounding allowance: D and W entries are off by at most eps each (two of each per
        # margin); score errors of at most eps_S scale each attention weight by at most
        # exp(2 eps_S), moving the weighted average by at most (exp(2 eps_S) - 1) max|w|.
        wmax = float(np.max(np.abs(w))) if P else 0.0
        wmax = max(wmax, float(np.max(np.abs(w_q))))
        allowance = 2 * self.eps_D + 2 * self.eps_W + (math.expm1(2 * self.eps_S)) * (wmax + 2 * self.eps_W)
        margins = self.D[tq, m] - self.D[tq, J] + lam_sound - allowance
        return float(margins.min())


def box_size(lo, hi) -> int:
    n = 1
    for l, h in zip(lo, hi):
        n *= int(h) - int(l) + 1
    return n

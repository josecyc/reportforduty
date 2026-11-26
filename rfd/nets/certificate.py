"""Certificates of accuracy for Max-of-K models, and their checker.

Every input t has a maximum m and a first position p where m occurs. The pair (m, p) splits
the input space into classes with no overlap:

    class (m, p):  t_i <= m-1 for i < p,   t_p = m,   t_i <= m for i > p.

A certificate gives, for any classes it likes, a tree of cuts inside the class's box:

    node := 1                      a leaf to check
          | 0                      a leaf left unclaimed (not checked, not counted)
          | [pos, cut, low, high]  low: t_pos <= cut ;  high: t_pos > cut

Leaves are disjoint by construction, so the checker never searches for overlaps. Each
claimed leaf is checked exactly (MaxOfK.check_box); the certified accuracy is the number of
inputs in proved leaves divided by V^k, an exact fraction.

File format (JSON):  {"model": "K10-v64/seed123", "classes": {"m,p": node, ...}}
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from fractions import Fraction

from .maxofk import MaxOfK, box_size

MAX_LEAVES = 3_000_000


@dataclass
class Result:
    model: str
    proved_inputs: int = 0
    total_inputs: int = 0
    leaves_checked: int = 0
    leaves_proved: int = 0
    classes: int = 0
    work: int = 0                  # machine-independent cost: sum over checked leaves of
                                   # (query tokens) x (other tokens) x (V-1)
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def bound(self) -> Fraction:
        return Fraction(self.proved_inputs, self.total_inputs) if self.total_inputs else Fraction(0)

    def summary(self) -> dict:
        return {"model": self.model, "proved_inputs": self.proved_inputs, "total_inputs": self.total_inputs,
                "bound": float(self.bound), "bound_exact": f"{self.bound.numerator}/{self.bound.denominator}",
                "leaves_checked": self.leaves_checked, "leaves_proved": self.leaves_proved,
                "classes": self.classes, "work": self.work, "seconds": round(self.seconds, 2),
                "errors": self.errors[:20]}


def class_box(k: int, m: int, p: int):
    if m == 0 and p != 0:
        return None
    lo = [0] * k
    hi = [m - 1 if i < p else m for i in range(k)]
    lo[p] = hi[p] = m
    return lo, hi


def check(model: MaxOfK, cert: dict, deadline: float | None = None) -> Result:
    k, V = model.k, model.V
    res = Result(model=model.name, total_inputs=V ** k)
    t0 = time.time()
    classes = cert.get("classes")
    if not isinstance(classes, dict):
        res.errors.append("certificate needs a 'classes' object")
        return res
    leaves = 0
    for key, tree in classes.items():
        try:
            m, p = (int(x) for x in key.split(","))
        except ValueError:
            res.errors.append(f"bad class key {key!r}; expected 'm,p'")
            continue
        if not (0 <= m < V and 0 <= p < k):
            res.errors.append(f"class {key} out of range")
            continue
        box = class_box(k, m, p)
        if box is None:
            res.errors.append(f"class {key} is empty")
            continue
        res.classes += 1
        stack = [(tree, list(box[0]), list(box[1]))]
        while stack:
            node, lo, hi = stack.pop()
            if node == 0:
                continue
            if node == 1:
                leaves += 1
                if leaves > MAX_LEAVES:
                    res.errors.append(f"more than {MAX_LEAVES} leaves")
                    res.seconds = time.time() - t0
                    return res
                if deadline and time.time() > deadline:
                    res.errors.append("ran out of checking time; leaves after this point were not counted")
                    res.seconds = time.time() - t0
                    return res
                res.leaves_checked += 1
                res.work += (hi[k - 1] - lo[k - 1] + 1) * sum(hi[i] - lo[i] + 1 for i in range(k - 1)) * (V - 1)
                ok, _ = model.check_box(lo, hi)
                if ok:
                    res.leaves_proved += 1
                    res.proved_inputs += box_size(lo, hi)
                continue
            if not (isinstance(node, list) and len(node) == 4):
                res.errors.append(f"class {key}: a node must be 0, 1 or [pos, cut, low, high]")
                break
            pos, cut, low, high = node
            if not (isinstance(pos, int) and isinstance(cut, int) and 0 <= pos < k and lo[pos] <= cut < hi[pos]):
                res.errors.append(f"class {key}: cut [{pos}, {cut}] is outside the box [{lo[pos]}, {hi[pos]}]")
                break
            lo2, hi2 = list(lo), list(hi)
            hi2[pos] = cut
            lo3, hi3 = list(lo), list(hi)
            lo3[pos] = cut + 1
            stack.append((low, lo2, hi2))
            stack.append((high, lo3, hi3))
    res.seconds = time.time() - t0
    return res


def load(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

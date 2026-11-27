#!/usr/bin/env python3
"""Check a claimed break of the frontier checkers: an input inside a proved box of a record
certificate that the model answers wrongly.

    python3 tools/verify_break.py K10-v64/seed123 63,12,40,5,0,0,0,0,0,7

1. Find the model's record certificate (certificates/K10-123.json) and the leaf holding the
   input: its class is (the maximum, the first position holding it), then the cuts decide.
2. Ask both checkers whether that leaf is proved.
3. Run the model on the input: a plain float64 forward pass written here, and the second
   checker on the one-input box (exact tables, interval bounds).

A break is confirmed when both checkers prove the leaf and the model's answer is wrong. Exit
code 0 for a confirmed break, 1 otherwise.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd import frontier  # noqa: E402
from rfd.nets import second_check  # noqa: E402
from rfd.nets.maxofk import MaxOfK  # noqa: E402


def forward(z, toks):
    E, P, Q, K, Vm, O, U = (z[k].astype(np.float64) for k in ("W_E", "W_pos", "W_Q", "W_K", "W_V", "W_O", "W_U"))
    h = E[toks] + P
    s = (h[-1] @ Q) @ (h @ K).T / np.sqrt(Q.shape[1])
    a = np.exp(s - s.max())
    a /= a.sum()
    return (h[-1] + a @ (h @ Vm @ O)) @ U


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    model, toks = sys.argv[1], [int(x) for x in sys.argv[2].replace(" ", "").split(",")]
    target = next((t for t in frontier.targets().values() if t.model == model), None)
    path = ROOT / "models" / "maxofk" / f"{model}.npz"
    if not target or not path.exists():
        print(f"no frontier target for {model}")
        return 1
    z = np.load(path)
    k, V = z["W_pos"].shape[0], z["W_E"].shape[0]
    if len(toks) != k or not all(0 <= t < V for t in toks):
        print(f"the input needs {k} tokens between 0 and {V - 1}")
        return 1
    cert_path = frontier.CERTS_DIR / f"{target.id}.json"
    if not cert_path.exists():
        print(f"NOT A BREAK: {target.id} has no record certificate yet")
        return 1
    cert = json.loads(cert_path.read_text(encoding="utf-8"))
    m = max(toks)
    p = toks.index(m)
    node = cert["classes"].get(f"{m},{p}", 0)
    lo = [0] * k
    hi = [m - 1 if i < p else m for i in range(k)]
    lo[p] = hi[p] = m
    while isinstance(node, list):
        pos, cut, low, high = node
        if toks[pos] <= cut:
            node, hi = low, hi[:pos] + [cut] + hi[pos + 1:]
        else:
            node, lo = high, lo[:pos] + [cut + 1] + lo[pos + 1:]
    print(f"input {toks}: maximum {m} first at position {p}; leaf lo={lo} hi={hi}, claimed: {node == 1}")
    if node != 1:
        print("NOT A BREAK: the record certificate does not claim this input")
        return 1
    first = MaxOfK.load(path).check_box(lo, hi)[0]
    sc = second_check.Model(path)
    second = sc.proves(m, lo, hi)
    print(f"leaf proved by the first checker: {first}; by the second checker: {second}")
    logits = forward(z, np.array(toks))
    others = np.delete(logits, m)
    margin = float(logits[m] - others.max())
    exact_right = sc.proves(m, toks, toks)
    print(f"float64 forward pass: answer {int(np.argmax(logits))}, margin of the right answer {margin:.6g}; "
          f"exact check of this one input: {'right' if exact_right else 'not proved right'}")
    if first and second and not exact_right and margin <= 0:
        print("BREAK CONFIRMED: both checkers proved a box containing an input the model gets wrong")
        return 0
    if first and second and not exact_right:
        print("UNCLEAR: the exact check cannot prove this input right, but the float pass says it is; send it in")
        return 1
    print("NOT A BREAK: the model answers this input correctly" if exact_right else "NOT A BREAK: the leaf is not proved by both checkers")
    return 1


if __name__ == "__main__":
    sys.exit(main())

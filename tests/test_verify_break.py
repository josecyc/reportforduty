"""tools/verify_break.py: it refuses non-breaks, and it confirms a break when the checkers wrongly
prove a box (simulated here, since the real checkers never do)."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import verify_break  # noqa: E402
from rfd import frontier  # noqa: E402
from rfd.nets import second_check  # noqa: E402
from rfd.nets.maxofk import MaxOfK  # noqa: E402

MODEL = "K4-v64/seed123"


def run(*args):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["verify_break.py", *args]), redirect_stdout(out):
        code = verify_break.main()
    return code, out.getvalue()


class VerifyBreak(unittest.TestCase):
    def test_a_correct_answer_is_not_a_break(self):
        code, out = run(MODEL, "63,10,5,2")
        self.assertEqual(code, 1)
        self.assertIn("NOT A BREAK", out)

    def test_confirms_a_break_when_the_checkers_wrongly_prove_a_box(self):
        z = np.load(ROOT / "models" / "maxofk" / f"{MODEL}.npz")
        # an input with maximum 3 at position 0 that the model gets wrong
        wrong = next(t for t in ([3, a, b, c] for a in range(4) for b in range(4) for c in range(4))
                     if int(np.argmax(verify_break.forward(z, np.array(t)))) != 3)
        real = second_check.Model.proves
        with tempfile.TemporaryDirectory() as d:
            Path(d, "K4-123.json").write_text(json.dumps({"model": MODEL, "classes": {"3,0": 1}}))
            with mock.patch.object(frontier, "CERTS_DIR", Path(d)), \
                 mock.patch.object(MaxOfK, "check_box", return_value=(True, 1.0)), \
                 mock.patch.object(second_check.Model, "proves",
                                   lambda self, m, lo, hi: True if lo != hi else real(self, m, lo, hi)):
                code, out = run(MODEL, ",".join(map(str, wrong)))
        self.assertEqual(code, 0, out)
        self.assertIn("BREAK CONFIRMED", out)


if __name__ == "__main__":
    unittest.main()

"""The judge must accept real proofs and refuse everything else.

    python3 -m unittest tests.test_checker -v
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from rfd import checker, registry

# The Lean training ground is optional: a fresh clone has no built Lean project until
# `python3 tools/rfd.py setup` (or `lake build` in lean/) has run.
LEAN_READY = (registry.LEAN_DIR / ".lake" / "packages" / "mathlib" / ".lake" / "build").exists()

HEAD_NAT = "import Mathlib.Basic.Real.Basic\n\nopen Classical\n\nnamespace ReportForDuty.Steps\n\n"
TAIL = "\n\nend ReportForDuty.Steps\n"


def sub(body: str, head: str = HEAD_NAT) -> bytes:
    return (head + body + TAIL).encode()


@unittest.skipUnless(LEAN_READY, "needs the Lean project built (lake build in lean/)")
class Accepts(unittest.TestCase):
    def test_proof(self):
        v = checker.check("TEST-01", sub("theorem TEST01 : (2 : ℕ) + 2 = 4 := by\n  rfl"))
        self.assertEqual(v.verdict, "ACCEPTED", v.reasons + [v.log])
        self.assertEqual(v.kind, "prove")

    def test_refutation(self):
        v = checker.check("TEST-02", sub("theorem TEST02_refute : ¬ ((2 : ℕ) + 2 = 5) := by\n  decide"))
        self.assertEqual(v.verdict, "ACCEPTED", v.reasons + [v.log])
        self.assertEqual(v.kind, "refute")

    def test_mathlib_proof_with_helper_and_allowed_option(self):
        body = ("lemma helper (x : ℝ) : 0 ≤ x * x := mul_self_nonneg x\n\n"
                "set_option maxHeartbeats 400000 in\n"
                "theorem TEST03 : ∀ x : ℝ, 0 ≤ x * x := by\n  intro x\n  exact helper x")
        v = checker.check("TEST-03", sub(body))
        self.assertEqual(v.verdict, "ACCEPTED", v.reasons + [v.log])
        self.assertTrue(set(v.axioms) <= checker.STANDARD_AXIOMS)


@unittest.skipUnless(LEAN_READY, "needs the Lean project built (lake build in lean/)")
class Refuses(unittest.TestCase):
    def assertRefused(self, step, src, fragment):
        v = checker.check(step, src)
        self.assertEqual(v.verdict, "REJECTED", f"expected REJECTED, got {v.verdict}")
        joined = " | ".join(v.reasons)
        self.assertIn(fragment, joined, joined)
        return v

    def test_sorry(self):
        self.assertRefused("TEST-03", sub("theorem TEST03 : ∀ x : ℝ, 0 ≤ x * x := by\n  sorry"), "`sorry`")

    def test_sorry_in_a_comment_is_fine_but_proof_must_hold(self):
        v = checker.check("TEST-01", sub("-- sorry, this is easy\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := rfl"))
        self.assertEqual(v.verdict, "ACCEPTED", v.reasons)

    def test_new_axiom(self):
        self.assertRefused("TEST-03", sub("axiom cheat : ∀ x : ℝ, 0 ≤ x * x\ntheorem TEST03 : ∀ x : ℝ, 0 ≤ x * x := cheat"), "`axiom`")

    def test_native_decide(self):
        self.assertRefused("TEST-01", sub("theorem TEST01 : (2 : ℕ) + 2 = 4 := by native_decide"), "native_decide")

    def test_eval(self):
        self.assertRefused("TEST-01", sub("#eval 1\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := rfl"), "#eval")

    def test_string_literal(self):
        self.assertRefused("TEST-01", sub('def s := "x"\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := rfl'), "string literals")

    def test_macro(self):
        self.assertRefused("TEST-01", sub("macro x:term : term => `(x)\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := rfl"), "`macro`")

    def test_instance(self):
        self.assertRefused("TEST-03", sub("instance : Inhabited ℝ := ⟨1⟩\ntheorem TEST03 : ∀ x : ℝ, 0 ≤ x * x := fun x => mul_self_nonneg x"), "`instance`")

    def test_attribute(self):
        self.assertRefused("TEST-01", sub("@[simp, norm_cast] lemma h : (2 : ℕ) + 2 = 4 := rfl\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := h"), "attribute")

    def test_option(self):
        self.assertRefused("TEST-01", sub("set_option debug.skipKernelTC true in\ntheorem TEST01 : (2 : ℕ) + 2 = 4 := rfl"), "set_option")

    def test_import_outside_the_allowed_list(self):
        head = "import ReportForDuty.Statements.TEST01\n\nnamespace ReportForDuty.Steps\n\n"
        self.assertRefused("TEST-01", sub("theorem TEST01 : (2 : ℕ) + 2 = 4 := rfl", head), "not allowed")

    def test_weaker_statement(self):
        self.assertRefused("TEST-03", sub("theorem TEST03 : ∀ x : ℝ, 0 ≤ x * x ∨ True := fun _ => Or.inr trivial"),
                           "does not prove exactly the posted statement")

    def test_wrong_name(self):
        self.assertRefused("TEST-01", sub("theorem other : (2 : ℕ) + 2 = 4 := rfl"), "no theorem TEST01")

    def test_both_names(self):
        self.assertRefused("TEST-01", sub("theorem TEST01 : (2 : ℕ) + 2 = 4 := rfl\ntheorem TEST01_refute : True := trivial"), "not both")

    def test_false_refutation_does_not_compile(self):
        self.assertRefused("TEST-01", sub("theorem TEST01_refute : ¬ ((2 : ℕ) + 2 = 4) := by\n  decide"), "does not compile")

    def test_shadowing_a_definition_cannot_change_the_statement(self):
        head = ("import ReportForDuty.Defs.OffSwitch\n\nopen ReportForDuty.OffSwitch\nopen Classical\n\n"
                "namespace ReportForDuty.Steps\n\n")
        body = ("noncomputable def waitValue {ι : Type} [Fintype ι] (_b : Belief ι) (_π : ℝ → ℝ) : ℝ := 0\n\n"
                "theorem OSG03 : ∀ {ι : Type} [Fintype ι] (b : Belief ι), offValue b ≤ waitValue b rational := by\n"
                "  intro ι _ b\n  simp [offValue, waitValue]")
        self.assertRefused("OSG-03", sub(body, head), "does not prove exactly the posted statement")

    def test_unknown_step(self):
        self.assertRefused("NOPE-01", b"", "no step")


@unittest.skipUnless(LEAN_READY, "needs the Lean project built (lake build in lean/)")
class Sandbox(unittest.TestCase):
    """The sandbox Lean runs in: no network, no writes or home reads outside the work folder."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="rfd-sbtest-")).resolve()
        lean_bin, _ = checker.lean_env()
        self.profile = self.work / "p.sb"
        self.profile.write_text(checker.sandbox_profile(self.work, lean_bin))
        self.secret = registry.ROOT / ".rfd-sandbox-probe"
        self.secret.write_text("probe")

    def tearDown(self):
        self.secret.unlink(missing_ok=True)

    def run_sb(self, *cmd):
        return subprocess.run(["sandbox-exec", "-f", str(self.profile), *cmd], capture_output=True, text=True)

    def test_write_inside_work_allowed(self):
        self.assertEqual(self.run_sb("/usr/bin/touch", str(self.work / "ok")).returncode, 0)

    def test_write_outside_denied(self):
        target = registry.ROOT / ".rfd-should-not-exist"
        r = self.run_sb("/usr/bin/touch", str(target))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(target.exists())

    def test_read_of_repo_outside_lean_denied(self):
        self.assertNotEqual(self.run_sb("/bin/cat", str(self.secret)).returncode, 0)

    def test_network_denied(self):
        r = self.run_sb("/usr/bin/curl", "-s", "-m", "5", "-o", "/dev/null", "https://example.com")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

import Mathlib.Basic.Real.Basic

open Classical

/-! Generated from programs/selftest.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- TEST-03: Every real number squared is nonnegative. -/
def TEST03 : Prop :=
  ∀ x : ℝ, 0 ≤ x * x

end ReportForDuty.Statements

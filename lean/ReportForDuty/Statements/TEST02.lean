import Mathlib.Basic.Real.Basic

open Classical

/-! Generated from programs/selftest.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- TEST-02: Two plus two is five (false; send a refutation). -/
def TEST02 : Prop :=
  (2 : ℕ) + 2 = 5

end ReportForDuty.Statements

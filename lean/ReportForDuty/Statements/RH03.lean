import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-03: On distributions, a constant reward gives every policy the same return. -/
def RH03 : Prop :=
  ∀ {n : ℕ} (c : ℝ), Trivial (Simplex n) (fun _ => c)

end ReportForDuty.Statements

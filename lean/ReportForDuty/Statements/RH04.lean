import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-04: On distributions, rescaling a reward by a nonnegative factor and shifting it by a constant never creates hacking. -/
def RH04 : Prop :=
  ∀ {n : ℕ} (r : Fin n → ℝ) (a b : ℝ), 0 ≤ a → Unhackable (Simplex n) r (fun i => a * r i + b)

end ReportForDuty.Statements

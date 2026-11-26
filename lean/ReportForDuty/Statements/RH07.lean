import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-07: On distributions, for any three outcomes in increasing order of true reward, an unhackable proxy's values lie on a straight line through the true values. -/
def RH07 : Prop :=
  ∀ {n : ℕ} (r₁ r₂ : Fin n → ℝ), Unhackable (Simplex n) r₁ r₂ → ∀ i j k, r₁ i < r₁ j → r₁ j < r₁ k → (r₂ j - r₂ i) * (r₁ k - r₁ j) = (r₂ k - r₂ j) * (r₁ j - r₁ i)

end ReportForDuty.Statements

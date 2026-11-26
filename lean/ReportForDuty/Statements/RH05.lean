import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-05: On distributions, if two rewards are unhackable, then whenever the true reward strictly prefers one outcome to another, the proxy does not prefer the opposite. -/
def RH05 : Prop :=
  ∀ {n : ℕ} (r₁ r₂ : Fin n → ℝ), Unhackable (Simplex n) r₁ r₂ → ∀ i j, r₁ i < r₁ j → r₂ i ≤ r₂ j

end ReportForDuty.Statements

import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-08: On distributions, two rewards are unhackable exactly when the true reward is constant or the proxy is a nonnegative rescaling of the true reward plus a constant. -/
def RH08 : Prop :=
  ∀ {n : ℕ} (r₁ r₂ : Fin n → ℝ), Unhackable (Simplex n) r₁ r₂ ↔ ((∃ c, ∀ i, r₁ i = c) ∨ (∃ a b : ℝ, 0 ≤ a ∧ ∀ i, r₂ i = a * r₁ i + b))

end ReportForDuty.Statements

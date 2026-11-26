import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-06: On distributions, if the true reward is not constant and the pair is unhackable, outcomes the true reward ties are also tied by the proxy. -/
def RH06 : Prop :=
  ∀ {n : ℕ} (r₁ r₂ : Fin n → ℝ), Unhackable (Simplex n) r₁ r₂ → (∃ k l, r₁ k ≠ r₁ l) → ∀ i j, r₁ i = r₁ j → r₂ i = r₂ j

end ReportForDuty.Statements

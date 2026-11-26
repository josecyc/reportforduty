import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-01: Unhackability is symmetric: swapping the true reward and the proxy changes nothing. -/
def RH01 : Prop :=
  ∀ {n : ℕ} (P : Set (Fin n → ℝ)) (r₁ r₂ : Fin n → ℝ), Unhackable P r₁ r₂ ↔ Unhackable P r₂ r₁

end ReportForDuty.Statements

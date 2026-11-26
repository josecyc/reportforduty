import ReportForDuty.Defs.RewardHacking

open ReportForDuty.RewardHacking
open Classical

/-! Generated from programs/rewardhacking.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- RH-02: A reward that gives every policy in the set the same return cannot be hacked against anything. -/
def RH02 : Prop :=
  ∀ {n : ℕ} (P : Set (Fin n → ℝ)) (r₁ r₂ : Fin n → ℝ), Trivial P r₁ → Unhackable P r₁ r₂

end ReportForDuty.Statements

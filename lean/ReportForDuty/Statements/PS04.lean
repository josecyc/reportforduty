import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-04: Over any finite set of scorings closed under retargeting along a copy of A inside B, B beats A at least as often as A beats B. -/
def PS04 : Prop :=
  ∀ {α : Type} (σ : Equiv.Perm α) (A B : Finset α) (Θ : Finset (α → ℝ)), CopiesInto σ A B → (∀ θ ∈ Θ, retarget σ θ ∈ Θ) → (Θ.filter (fun θ => Beats θ A B)).card ≤ (Θ.filter (fun θ => Beats θ B A)).card

end ReportForDuty.Statements

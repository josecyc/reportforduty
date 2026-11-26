import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-06: For every scoring, among all relabellings of the outcomes, at least as many make B beat A as make A beat B, when A and B are disjoint and B has at least as many outcomes as A. -/
def PS06 : Prop :=
  ∀ {α : Type} [Fintype α] [DecidableEq α] (A B : Finset α) (θ : α → ℝ), Disjoint A B → A.card ≤ B.card → (Finset.univ.filter (fun τ : Equiv.Perm α => Beats (retarget τ θ) A B)).card ≤ (Finset.univ.filter (fun τ : Equiv.Perm α => Beats (retarget τ θ) B A)).card

end ReportForDuty.Statements

import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-05: If B holds k disjoint copies of A, each moved there by its own symmetry that leaves everything else in place, B beats A at least k times as often as A beats B. -/
def PS05 : Prop :=
  ∀ {α : Type} [DecidableEq α] (k : ℕ) (σ : Fin k → Equiv.Perm α) (A B : Finset α) (Θ : Finset (α → ℝ)), (∀ i, CopiesInto (σ i) A B) → (∀ i, Disjoint A (A.image (σ i))) → (∀ i j, i ≠ j → Disjoint (A.image (σ i)) (A.image (σ j))) → (∀ i x, x ∉ A → x ∉ A.image (σ i) → σ i x = x) → (∀ i, ∀ θ ∈ Θ, retarget (σ i) θ ∈ Θ) → k * (Θ.filter (fun θ => Beats θ A B)).card ≤ (Θ.filter (fun θ => Beats θ B A)).card

end ReportForDuty.Statements

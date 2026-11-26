import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-01: More options are at least as good: if A is nonempty and contained in B, B is at least as good as A under every scoring of outcomes. -/
def PS01 : Prop :=
  ∀ {α : Type} (θ : α → ℝ) (A B : Finset α), A.Nonempty → A ⊆ B → AtLeast θ B A

end ReportForDuty.Statements

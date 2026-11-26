import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-02: Two option sets cannot each strictly beat the other. -/
def PS02 : Prop :=
  ∀ {α : Type} (θ : α → ℝ) (A B : Finset α), Beats θ A B → ¬ Beats θ B A

end ReportForDuty.Statements

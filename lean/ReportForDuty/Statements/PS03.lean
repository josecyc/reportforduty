import ReportForDuty.Defs.Retargeting

open ReportForDuty.Retargeting
open Classical

/-! Generated from programs/retargeting.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- PS-03: Retargeting along a copy of A inside B turns every scoring under which A beats B into one under which B beats A. -/
def PS03 : Prop :=
  ∀ {α : Type} (σ : Equiv.Perm α) (A B : Finset α) (θ : α → ℝ), CopiesInto σ A B → Beats θ A B → Beats (retarget σ θ) B A

end ReportForDuty.Statements

import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-09: Waiting is never worse, whatever the robot believes, exactly when the human never errs on an action that is clearly good or clearly bad. -/
def OSG09 : Prop :=
  ∀ (π : ℝ → ℝ), IsPolicy π → ((∀ (ι : Type) [Fintype ι] (b : Belief ι), 0 ≤ incentive b π) ↔ ((∀ u, 0 < u → π u = 1) ∧ (∀ u, u < 0 → π u = 0)))

end ReportForDuty.Statements

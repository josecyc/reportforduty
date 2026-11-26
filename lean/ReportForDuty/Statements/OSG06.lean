import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-06: With a rational human, the incentive to wait is strictly positive exactly when the robot gives positive probability both to the action being good and to it being bad. -/
def OSG06 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι), 0 < incentive b rational ↔ ((∃ i, 0 < b.p i ∧ 0 < b.u i) ∧ (∃ j, 0 < b.p j ∧ b.u j < 0))

end ReportForDuty.Statements

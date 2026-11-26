import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-04: With a rational human, the robot's incentive to wait is never negative. -/
def OSG04 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι), 0 ≤ incentive b rational

end ReportForDuty.Statements

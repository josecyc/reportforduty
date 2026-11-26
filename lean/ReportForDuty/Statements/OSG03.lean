import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-03: With a rational human, waiting is worth at least as much as switching off. -/
def OSG03 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι), offValue b ≤ waitValue b rational

end ReportForDuty.Statements

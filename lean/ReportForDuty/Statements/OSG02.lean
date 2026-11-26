import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-02: With a rational human, waiting is worth at least as much as acting now. -/
def OSG02 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι), actValue b ≤ waitValue b rational

end ReportForDuty.Statements

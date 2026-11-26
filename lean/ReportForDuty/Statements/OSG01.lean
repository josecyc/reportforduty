import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-01: With a rational human, waiting is worth the expected good part of the action: the average of the utility where it is positive, and zero where it is not. -/
def OSG01 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι), waitValue b rational = b.E (fun u => max u 0)

end ReportForDuty.Statements

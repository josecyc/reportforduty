import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-05: A robot that is certain of the utility gains nothing by waiting. -/
def OSG05 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι) (c : ℝ), (∀ i, 0 < b.p i → b.u i = c) → incentive b rational = 0

end ReportForDuty.Statements

import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-08: A sufficiently unreliable human can make waiting strictly worse than the robot's best alternative. -/
def OSG08 : Prop :=
  ∃ (b : Belief (Fin 2)) (π : ℝ → ℝ), IsPolicy π ∧ incentive b π < 0

end ReportForDuty.Statements

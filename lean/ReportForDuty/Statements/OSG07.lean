import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! Generated from programs/offswitch.json by tools/gen_statements.py.
Do not edit by hand. -/

namespace ReportForDuty.Statements

/-- OSG-07: A human who errs with probability at most ε costs at most ε times the expected size of the utility: the incentive to wait is at least −ε·E|U|. -/
def OSG07 : Prop :=
  ∀ {ι : Type} [Fintype ι] (b : Belief ι) (ε : ℝ) (π : ℝ → ℝ), 0 ≤ ε → ErrsAtMost ε π → -(ε * b.E (fun u => |u|)) ≤ incentive b π

end ReportForDuty.Statements

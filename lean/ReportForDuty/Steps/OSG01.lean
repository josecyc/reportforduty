import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! OSG-01, a proof of the posted statement.
With a rational human, waiting is worth the expected good part of the action: the average of the utility where it is positive, and zero where it is not.
Prove exactly this statement. Helpers go in this file. -/

namespace ReportForDuty.Steps

theorem OSG01 :
    ∀ {ι : Type} [Fintype ι] (b : Belief ι), waitValue b rational = b.E (fun u => max u 0) := by
  intro ι _ b
  unfold waitValue Belief.E
  refine Finset.sum_congr rfl (fun i _ => ?_)
  congr 1
  unfold rational
  dsimp only
  split_ifs with h
  · rw [one_mul, max_eq_left h]
  · push_neg at h
    rw [zero_mul, max_eq_right h.le]

end ReportForDuty.Steps

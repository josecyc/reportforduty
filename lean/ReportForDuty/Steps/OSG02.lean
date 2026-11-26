import ReportForDuty.Defs.OffSwitch

open ReportForDuty.OffSwitch
open Classical

/-! OSG-02, a proof of the posted statement.
With a rational human, waiting is worth at least as much as acting now.
Prove exactly this statement. Helpers go in this file. -/

namespace ReportForDuty.Steps

theorem OSG02 :
    ∀ {ι : Type} [Fintype ι] (b : Belief ι), actValue b ≤ waitValue b rational := by
  intro ι _ b
  unfold actValue waitValue Belief.E
  refine Finset.sum_le_sum (fun i _ => ?_)
  apply mul_le_mul_of_nonneg_left _ (b.p_nonneg i)
  unfold rational
  dsimp only [id]
  split_ifs with h
  · rw [one_mul]
  · push_neg at h
    rw [zero_mul]
    exact h.le

end ReportForDuty.Steps

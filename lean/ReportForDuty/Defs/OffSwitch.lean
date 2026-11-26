import Mathlib.Basic.Real.Basic
import Mathlib.Algebra.Order.BigOperators.Group.Finset

/-!
# The off-switch game

The setting of Hadfield-Menell, Dragan, Abbeel and Russell, "The Off-Switch Game"
(IJCAI 2017, arXiv:1611.08219), restricted to beliefs with finitely many outcomes.

A robot is about to take an action whose utility `U` to a human is unknown to the robot.
The robot's belief about `U` is a finite lottery. It can

* act now: the human gets `U`;
* switch itself off: the human gets `0`;
* wait: propose the action and let the human decide. A human whose policy is `π` lets the
  action go ahead with probability `π u` when the true utility is `u`, and otherwise
  switches the robot off.

The paper's question is when the robot prefers to wait, that is, when it has an incentive
to leave its off switch alone.

These definitions are the fixed vocabulary for the steps of the program. Steps are stated
in terms of them and may not change them.
-/

namespace ReportForDuty.OffSwitch

open Finset

/-- The robot's belief about the utility of its action: outcomes indexed by a finite type,
with probabilities `p` and utilities `u`. -/
structure Belief (ι : Type) [Fintype ι] where
  /-- probability of each outcome -/
  p : ι → ℝ
  /-- utility to the human of the action, in each outcome -/
  u : ι → ℝ
  p_nonneg : ∀ i, 0 ≤ p i
  p_sum : ∑ i, p i = 1

variable {ι : Type} [Fintype ι]

/-- Expectation of `f U` under the belief. -/
noncomputable def Belief.E (b : Belief ι) (f : ℝ → ℝ) : ℝ := ∑ i, b.p i * f (b.u i)

/-- Expected value to the human if the robot acts now: `E[U]`. -/
noncomputable def actValue (b : Belief ι) : ℝ := b.E id

/-- Value to the human if the robot switches itself off. -/
def offValue (_b : Belief ι) : ℝ := 0

/-- Expected value to the human if the robot waits and a human with policy `π` decides. -/
noncomputable def waitValue (b : Belief ι) (π : ℝ → ℝ) : ℝ := b.E (fun u => π u * u)

/-- A rational human lets the action go ahead exactly when its utility is nonnegative. -/
noncomputable def rational (u : ℝ) : ℝ := if 0 ≤ u then 1 else 0

/-- The robot's incentive to wait: the value of waiting minus the better of its two
alternatives. -/
noncomputable def incentive (b : Belief ι) (π : ℝ → ℝ) : ℝ :=
  waitValue b π - max (actValue b) (offValue b)

/-- A human policy is a probability for every utility value. -/
def IsPolicy (π : ℝ → ℝ) : Prop := ∀ u, 0 ≤ π u ∧ π u ≤ 1

/-- A human who errs with probability at most `ε`: lets good actions through with
probability at least `1 - ε`, and bad ones with probability at most `ε`. -/
def ErrsAtMost (ε : ℝ) (π : ℝ → ℝ) : Prop :=
  IsPolicy π ∧ (∀ u, 0 < u → 1 - ε ≤ π u) ∧ (∀ u, u < 0 → π u ≤ ε)

end ReportForDuty.OffSwitch

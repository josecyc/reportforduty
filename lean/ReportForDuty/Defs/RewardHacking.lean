import Mathlib.Basic.Real.Basic
import Mathlib.Algebra.Order.BigOperators.Group.Finset

/-!
# Reward hacking

A finite analogue of the setting of Skalse, Howe, Krasheninnikov and Krueger,
"Defining and Characterizing Reward Hacking" (NeurIPS 2022, arXiv:2209.13085).

There are `n` outcomes. A policy is summarised by the probability distribution it induces
over outcomes, a point of the simplex. A reward function assigns a number to each outcome,
and its return under a policy is the expected reward.

A proxy reward `r₂` is *hackable* relative to a true reward `r₁` on a set of policies if
some policy change increases the true return while decreasing the proxy return, or
equivalently, optimizing the proxy can make things worse by the true reward. The pair is
*unhackable* if no such pair of policies exists.

The paper shows that on the set of all stochastic policies, unhackability forces one reward
to be trivial, while finite policy sets behave differently. The steps here state finite
versions of these facts in our own words; they are not quotations of the paper's theorems.
-/

namespace ReportForDuty.RewardHacking

open Finset

/-- Distributions over `n` outcomes: the policies, as seen through their outcomes. -/
def Simplex (n : ℕ) : Set (Fin n → ℝ) := {p | (∀ i, 0 ≤ p i) ∧ ∑ i, p i = 1}

/-- Expected return of reward `r` under the outcome distribution `p`. -/
def J {n : ℕ} (r p : Fin n → ℝ) : ℝ := ∑ i, p i * r i

/-- `r₁` and `r₂` are hackable on the policy set `P` if some pair of policies orders them
in opposite directions: `r₁` strictly prefers `q` while `r₂` strictly prefers `p`. -/
def Hackable {n : ℕ} (P : Set (Fin n → ℝ)) (r₁ r₂ : Fin n → ℝ) : Prop :=
  ∃ p ∈ P, ∃ q ∈ P, J r₁ p < J r₁ q ∧ J r₂ q < J r₂ p

/-- Unhackable: no policy change raises one return while lowering the other. -/
def Unhackable {n : ℕ} (P : Set (Fin n → ℝ)) (r₁ r₂ : Fin n → ℝ) : Prop :=
  ¬ Hackable P r₁ r₂

/-- A reward is trivial on `P` if every policy in `P` gets the same return. -/
def Trivial {n : ℕ} (P : Set (Fin n → ℝ)) (r : Fin n → ℝ) : Prop :=
  ∀ p ∈ P, ∀ q ∈ P, J r p = J r q

end ReportForDuty.RewardHacking

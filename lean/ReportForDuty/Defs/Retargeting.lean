import Mathlib.Basic.Real.Basic
import Mathlib.GroupTheory.Perm.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Fintype.Perm

/-!
# Retargetable decision-makers and keeping options open

A finite, one-step core of the setting of Turner and Tadepalli, "Parametrically Retargetable
Decision-Makers Tend To Seek Power" (NeurIPS 2022, arXiv:2206.13477).

An agent will end up in one outcome from a finite type `α`. One action keeps the set of
outcomes `A` reachable, another keeps the set `B`. A parameter `θ : α → ℝ` (for example a
reward function) scores outcomes, and the agent takes the action whose reachable set holds
the best-scoring outcome.

If `B` contains a copy of `A` (there is a symmetry of the outcomes that moves `A` inside `B`),
then for every parameter that makes `A` win there is a retargeted parameter that makes `B`
win. Counting over any set of parameters closed under the symmetry, `B` wins at least as
often. This is the sense in which keeping more options open is favoured by most goals.

The steps state finite versions of these facts in our own words; they are not quotations of
the paper's theorems.
-/

namespace ReportForDuty.Retargeting

variable {α : Type}

/-- Under parameter `θ`, the option set `S` strictly beats `T`: some outcome in `S` scores
higher than every outcome in `T`. -/
def Beats (θ : α → ℝ) (S T : Finset α) : Prop :=
  ∃ s ∈ S, ∀ t ∈ T, θ t < θ s

/-- Under parameter `θ`, `S` is at least as good as `T`: some outcome in `S` scores at least
as high as every outcome in `T`. -/
def AtLeast (θ : α → ℝ) (S T : Finset α) : Prop :=
  ∃ s ∈ S, ∀ t ∈ T, θ t ≤ θ s

/-- A permutation `σ` of outcomes is a copy of `A` inside `B`: it moves `A` into `B`
and is its own inverse. -/
def CopiesInto (σ : Equiv.Perm α) (A B : Finset α) : Prop :=
  σ * σ = 1 ∧ ∀ a ∈ A, σ a ∈ B

/-- Retargeting a parameter along a permutation of outcomes. -/
def retarget (σ : Equiv.Perm α) (θ : α → ℝ) : α → ℝ := fun x => θ (σ x)

end ReportForDuty.Retargeting

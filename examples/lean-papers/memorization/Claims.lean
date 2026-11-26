import MemorizationCapacity
import Paper

/-!
# Section 3's capacity experiment, checked against our rerun

`MemorizationCapacity.lean` is `trackio export` of the runs `train_capacity.py` logged on
Hugging Face Jobs: GPT-2 models of four shapes (1 or 2 layers, width 32 or 64), each
trained on datasets of N uniformly random sequences (V = 2048, S = 64) for 30,000 steps
in bf16. Memorized bits are the data's entropy minus the model's code length for it,
so a model can only memorize as much as it has learned: every capacity below is a lower
bound on the true capacity. The paper trains for 10⁶ steps; we train for 3·10⁴ with a
cosine schedule, so the learning rate has decayed to zero by the last evaluation.
-/

open Trackio Exact MemorizationCapacity

namespace Claims

def shape (r : Run) : Option (Nat × Nat) := do
  return ((← (cfg r .n_layer).bind Q.toNat?), (← (cfg r .d_model).bind Q.toNat?))

def sizeN (r : Run) : Option Nat := (cfg r .N).bind Q.toNat?

def models : List (Nat × Nat) := [(1, 32), (2, 32), (1, 64), (2, 64)]

def runsOf (m : Nat × Nat) : List Run := runs.filter fun r => shape r == some m

def params (m : Nat × Nat) : Nat := Paper.gpt2Params m.1 m.2 2048 64

/-- The model `train_capacity.py` built is the one the paper's Table 1 counts: its logged
parameter count is `Paper.gpt2Params` for its shape. -/
theorem params_match_gpt2_formula :
    runs.all (fun r => match shape r, atStep r .model_params 0 with
      | some m, some p => decide (p ≈ q (params m))
      | _, _ => false) = true := by
  decide +kernel

/-- The data's entropy is exactly `N · (S−1) · log₂ V` bits. -/
theorem entropy_is_exact :
    runs.all (fun r => match sizeN r, atStep r .data_entropy_bits 0 with
      | some n, some h => decide (h ≈ q (n * 63 * 11))
      | _, _ => false) = true := by
  decide +kernel

/-- Bits memorized at the end of training. -/
def memEnd (r : Run) : Option Q := final r .mem_bits

/-- A model's capacity, as the paper defines it: the most it memorizes over all dataset
sizes. -/
def capacity (m : Nat × Nat) : Option Q :=
  ((runsOf m).filterMap memEnd).foldl (fun acc x => some (match acc with
    | none => x
    | some a => Q.max a x)) none

def alpha (m : Nat × Nat) : Option Q := do return div (← capacity m) (q (params m))

/-- Table 1's bf16 capacity for this shape. -/
def paperCapacity (m : Nat × Nat) : Option Q :=
  (Paper.table1.find? fun r => r.L == m.1 && r.d == m.2).map (Paper.val ·.capBf16)

def sizesOf (m : Nat × Nat) : List Nat := (runsOf m).filterMap sizeN

def runWith (m : Nat × Nat) (n : Nat) : Option Run := (runsOf m).find? (sizeN · == some n)

def smallest (m : Nat × Nat) : Option Run := do runWith m (← (sizesOf m).min?)

def largest (m : Nat × Nat) : Option Run := do runWith m (← (sizesOf m).max?)

def fractionEnd (r : Run) : Option Q := final r .mem_fraction_of_entropy

/-- Every model was trained on four dataset sizes spanning a factor of eight. -/
theorem four_sizes_per_model :
    runs.length = 16 ∧
    models.all (fun m => (runsOf m).length == 4 &&
      (do return (← (sizesOf m).max?) == 8 * (← (sizesOf m).min?)) == some true) = true := by
  decide +kernel

/-! ## What the rerun supports -/

/-- "Models memorize their training data until they reach capacity": on the smallest
dataset every model memorizes more than 99.9% of its entropy. -/
theorem small_datasets_memorized :
    models.all (fun m => ((smallest m).bind fractionEnd).map (fun f => decide (0.999 < f))
      == some true) = true := by
  decide +kernel

/-- "...at which point memorization plateaus": over the three largest datasets, a fourfold
increase in N, each model's memorized bits stay within 5% of each other, while the largest
dataset is at most 26% memorized. More data does not buy more memorization. -/
theorem memorization_plateaus :
    models.all (fun m =>
      let big := ((runsOf m).filter fun r => sizeN r != (do (sizesOf m).min?)).filterMap memEnd
      big.length == 3 &&
      big.all (fun x => big.all fun y => decide (x ≤ 1.05 * y)) &&
      ((largest m).bind fractionEnd).map (fun f => decide (f ≤ 0.26)) == some true) = true := by
  decide +kernel

/-- Capacity grows with parameter count, and bits per parameter stay within 13% across a
threefold range of model sizes, which is the paper's "capacity is roughly proportional to
parameters". -/
theorem capacity_scales_with_params :
    (do
      let caps ← models.mapM capacity
      let as ← models.mapM alpha
      return (caps.zip caps.tail).all (fun (a, b) => decide (a < b)) &&
        as.all (fun x => as.all fun y => decide (x ≤ 1.13 * y))) = some true := by
  decide +kernel

/-! ## What the rerun does not reach -/

/-- Our capacities are between two thirds and five sixths of Table 1's bf16 capacities,
and every α is below the paper's 3.5–3.6 bits per parameter. Since memorization at 3·10⁴
steps is a lower bound, this neither confirms nor contradicts Table 1: it says how much
of the paper's number a 30× shorter schedule reaches. -/
theorem below_paper_capacity :
    models.all (fun m => (do
      let c ← capacity m
      let p ← paperCapacity m
      let a ← alpha m
      return decide (2 * p < 3 * c) && decide (6 * c < 5 * p) && decide (a < 3.5)) == some true)
      = true := by
  decide +kernel

/-- The range of our α: from 2.70 (1 layer, width 32) to 3.06 (2 layers, width 64). -/
theorem alpha_range :
    (alpha (1, 32)).map (fun a => decide (2.70 < a) && decide (a < 2.71)) = some true ∧
    (alpha (2, 64)).map (fun a => decide (3.05 < a) && decide (a < 3.06)) = some true := by
  decide +kernel

end Claims

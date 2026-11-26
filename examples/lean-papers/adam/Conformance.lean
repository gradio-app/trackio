import AdamRuns
import Spec

/-!
# Does the code we ran implement Algorithm 1?

Every Adam run in `AdamRuns` logged a probe at step 0: `torch.optim.Adam` (float64,
α = 0.001, β₁ = 0.9, β₂ = 0.999, ε = 1e-8) applied for ten steps to three parameters
with fixed gradients. Here `Adam.run` computes the same ten steps exactly from
Algorithm 1, and every logged value must lie within 1e-12 of Lean's enclosure.

The tolerance is tight enough to tell Algorithm 1 apart from its common variants:
the same check fails for ε inside the square root (`√(v̂ + ε)`) and for Adam
without bias correction, so the probe pins down the update rule, not just "some
Adam".
-/

open Trackio Exact AdamRuns

namespace Conformance

def init : List Q := [0.5, -0.25, 1.0]

/-- The probe's gradients, `((7t + 3i) mod 9 − 4) / 8` for step `t` = 0..9 and parameter `i`. -/
def grad (t i : Nat) : Q := q (((7 * t + 3 * i) % 9 : Nat) - 4 : Int) 8

def grads (i : Nat) : List Q := (List.range 10).map (grad · i)

def probe : Nat → Nat → Option Metric
  | 1, 0 => some .probe_adam_t1_p0 | 1, 1 => some .probe_adam_t1_p1 | 1, 2 => some .probe_adam_t1_p2
  | 2, 0 => some .probe_adam_t2_p0 | 2, 1 => some .probe_adam_t2_p1 | 2, 2 => some .probe_adam_t2_p2
  | 3, 0 => some .probe_adam_t3_p0 | 3, 1 => some .probe_adam_t3_p1 | 3, 2 => some .probe_adam_t3_p2
  | 4, 0 => some .probe_adam_t4_p0 | 4, 1 => some .probe_adam_t4_p1 | 4, 2 => some .probe_adam_t4_p2
  | 5, 0 => some .probe_adam_t5_p0 | 5, 1 => some .probe_adam_t5_p1 | 5, 2 => some .probe_adam_t5_p2
  | 6, 0 => some .probe_adam_t6_p0 | 6, 1 => some .probe_adam_t6_p1 | 6, 2 => some .probe_adam_t6_p2
  | 7, 0 => some .probe_adam_t7_p0 | 7, 1 => some .probe_adam_t7_p1 | 7, 2 => some .probe_adam_t7_p2
  | 8, 0 => some .probe_adam_t8_p0 | 8, 1 => some .probe_adam_t8_p1 | 8, 2 => some .probe_adam_t8_p2
  | 9, 0 => some .probe_adam_t9_p0 | 9, 1 => some .probe_adam_t9_p1 | 9, 2 => some .probe_adam_t9_p2
  | 10, 0 => some .probe_adam_t10_p0 | 10, 1 => some .probe_adam_t10_p1 | 10, 2 => some .probe_adam_t10_p2
  | _, _ => none

/-- A one-coordinate Adam-like update: `θ_t = θ_{t-1} − α · m_t / d(v_t)`, where
`moments` gives `(m_t, v_t)` after the first `t` gradients and `denom` turns `v_t`
into an enclosure of the denominator. `Adam.run` is this with bias-corrected
moments and `d(v) = √v + ε`. -/
def runWith (moments : List Q → Q × Q) (denom : Q → Option Interval) (theta0 : Q)
    (gs : List Q) : Option (List Interval) :=
  let steps := (List.range gs.length).map fun i => moments (gs.take (i + 1))
  let result := steps.foldlM (fun (acc : Interval × List Interval) (mv : Q × Q) => do
    let d ← denom mv.2
    let delta := Interval.divPos (Interval.exact (mul 0.001 mv.1)) d
    let theta := Interval.round (Interval.sub acc.1 delta)
    return (theta, acc.2 ++ [theta])) (Interval.exact theta0, [])
  result.map (·.2)

def epsOutside (v : Q) : Option Interval := do
  let s ← sqrt v
  return Interval.add s (Interval.exact 1e-8)

def epsInside (v : Q) : Option Interval := sqrt (add v 1e-8)

def algorithm1 (theta0 : Q) (gs : List Q) : Option (List Interval) :=
  Adam.run Adam.defaults 0.001 1e-8 theta0 gs

def epsInsideSqrt (theta0 : Q) (gs : List Q) : Option (List Interval) :=
  runWith (Adam.corrected Adam.defaults) epsInside theta0 gs

def noBiasCorrection (theta0 : Q) (gs : List Q) : Option (List Interval) :=
  runWith (Adam.moments Adam.defaults) epsOutside theta0 gs

/-- `rule`'s iterates for the three probe parameters, indexed `[i][t-1]`. -/
def expected (rule : Q → List Q → Option (List Interval)) : Option (List (List Interval)) :=
  (List.range 3).mapM fun i => rule (init.getD i 0) (grads i)

def within (x : Q) (iv : Interval) (tol : Q) : Bool :=
  decide (iv.lo - tol ≤ x) && decide (x ≤ iv.hi + tol)

/-- Every probe value `r` logged matches `rule` to within `tol`. -/
def agrees (rule : Q → List Q → Option (List Interval)) (tol : Q) (r : Run) : Option Bool := do
  let exp ← expected rule
  allOf ((List.range 10).flatMap fun t => (List.range 3).map fun i => (t + 1, i)) fun (t, i) => do
    let m ← probe t i
    let x ← atStep r m 0
    let iv ← (exp.getD i [])[t - 1]?
    return within x iv tol

def adamRuns : List Run := runs.filter fun r => cfgStr r .optimizer == some "adam"

theorem every_adam_run_implements_algorithm_1 :
    adamRuns.length = 19 ∧ holds (allOf adamRuns (agrees algorithm1 1e-12)) := by
  decide +kernel

theorem eps_inside_sqrt_does_not_match :
    adamRuns.all (fun r => agrees epsInsideSqrt 1e-12 r == some false) = true := by
  decide +kernel

theorem no_bias_correction_does_not_match :
    adamRuns.all (fun r => agrees noBiasCorrection 1e-12 r == some false) = true := by
  decide +kernel

/-- All runs ran the same script, on Hugging Face Jobs. `trackio verify` checks this
hash against `train_optimizers.py` and against the copy the job executed. -/
theorem one_script_one_job :
    (runs.map codeSha256).eraseDups.length = 1 ∧ (runs.map codeSha256).all Option.isSome ∧
    (runs.map hfJobId).eraseDups.length = 1 ∧ (runs.map hfJobId).all Option.isSome := by
  decide +kernel

end Conformance

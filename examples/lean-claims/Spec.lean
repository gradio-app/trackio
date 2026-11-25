import Trackio

/-!
# The method of "Attention Is All You Need", as an executable Lean spec

The training code logs facts about itself to Trackio: the learning rate it used,
its parameter count, and the outputs of its attention layer on a fixed probe.
This file defines what the paper says those facts should be, so `Claims.lean`
can check every logged value against the spec.

Everything is exact rational arithmetic. Softmax needs `exp`, which is not
rational, so `expNeg` returns an interval proven to contain the true value
(a Taylor partial sum plus a Lagrange remainder bound). A logged value
conforms when it lies within float32 tolerance of that interval.
-/

open Trackio

namespace Spec

/-! ## Exact arithmetic with normalized fractions -/

def norm (a : Q) : Q :=
  let g := Nat.gcd a.num.natAbs a.den
  if g ≤ 1 then a else ⟨a.num / (g : Int), a.den / g⟩

def add (a b : Q) : Q := norm (a + b)
def mul (a b : Q) : Q := norm (a * b)
def sum (xs : List Q) : Q := xs.foldl add 0

/-- `1 / a`, for `a > 0`. -/
def inv (a : Q) : Q := ⟨(a.den : Int), a.num.toNat⟩

def dot (xs ys : List Q) : Q := sum (List.zipWith mul xs ys)

/-! ## Intervals -/

/-- A closed interval `[lo, hi]` of rationals. -/
structure Interval where
  lo : Q
  hi : Q

namespace Interval

def exact (x : Q) : Interval := ⟨x, x⟩

def add (a b : Interval) : Interval := ⟨Spec.add a.lo b.lo, Spec.add a.hi b.hi⟩

/-- `a * w` for an exact rational `w`. -/
def scale (a : Interval) (w : Q) : Interval :=
  if decide (w < 0) then ⟨mul a.hi w, mul a.lo w⟩ else ⟨mul a.lo w, mul a.hi w⟩

def sum (xs : List Interval) : Interval := xs.foldl add (exact 0)

/-- `x` is within `tol` of the interval. -/
def contains (a : Interval) (x tol : Q) : Bool :=
  decide (a.lo - tol ≤ x) && decide (x ≤ a.hi + tol)

end Interval

/-! ## exp and softmax -/

/-- The Taylor partial sum `1 + y + … + y^n/n!` and its last term `y^n/n!`. -/
def taylor (y : Q) (n : Nat) : Q × Q :=
  (List.range n).foldl
    (fun (acc : Q × Q) k =>
      let t := mul acc.2 (mul y (q 1 (k + 1)))
      (Spec.add acc.1 t, t))
    (1, 1)

/-- An interval containing `exp (-y)`, for `0 ≤ y ≤ 4`. With `S` the Taylor sum to
30 terms, `S ≤ exp y ≤ S + 81 · y^31/31!` (Lagrange remainder, using
`exp y ≤ exp 4 < 3^4 = 81`), so `exp (-y) ∈ [1/(S + R), 1/S]`. -/
def expNeg (y : Q) : Option Interval :=
  if decide (y < 0) || decide (4 < y) then none
  else
    let (s, last) := taylor y 30
    let r := mul (mul last (mul y (q 1 31))) 81
    some ⟨inv (Spec.add s r), inv s⟩

/-- Intervals containing `softmax s`. Shifting by the maximum is exact:
`softmax s = softmax (s - max s)`. -/
def softmax (s : List Q) : Option (List Interval) := do
  let m ← s.foldl
    (fun acc x => some (match acc with | none => x | some a => Q.max a x))
    (none : Option Q)
  let es ← s.mapM fun x => expNeg (norm (m - x))
  let total := Interval.sum es
  return es.map fun e => ⟨mul e.lo (inv total.hi), mul e.hi (inv total.lo)⟩

/-! ## Multi-head attention (Section 3.2) -/

/-- One multi-head self-attention layer. Projection matrices are stored as
`h` heads stacked along the output dimension, rows first:
`wq r c` is row `r` of `[W₁^Q; …; W_h^Q]ᵀ`, and `wo o r` maps the
concatenated heads back to `d_model`. -/
structure MHA where
  dModel : Nat
  h : Nat
  dk : Nat
  dv : Nat
  sqrtDk : Q
  wq : Nat → Nat → Q
  wk : Nat → Nat → Q
  wv : Nat → Nat → Q
  wo : Nat → Nat → Q

def project (w : Nat → Nat → Q) (rows cols : Nat) (x : List Q) : List Q :=
  (List.range rows).map fun r => sum ((List.range cols).map fun c => mul (x.getD c 0) (w r c))

/-- `MultiHead(X, X, X)` at position `t` (Section 3.2.2), where
`head_i = softmax(Q_i K_iᵀ / √d_k) V_i` (Equation 1) and position `t` may only
attend to `allowed t`. -/
def MHA.output (m : MHA) (x : List (List Q)) (allowed : Nat → List Nat) (t : Nat) :
    Option (List Interval) := do
  let qs := x.map (project m.wq (m.h * m.dk) m.dModel)
  let ks := x.map (project m.wk (m.h * m.dk) m.dModel)
  let vs := x.map (project m.wv (m.h * m.dv) m.dModel)
  let keys := allowed t
  let heads ← (List.range m.h).mapM fun i => do
    let slice := fun (v : List Q) => (List.range m.dk).map fun j => v.getD (i * m.dk + j) 0
    let qt := slice (qs.getD t [])
    let scores := keys.map fun u => mul (dot qt (slice (ks.getD u []))) (inv m.sqrtDk)
    let p ← softmax scores
    return (List.range m.dv).map fun j =>
      Interval.sum (List.zipWith (fun pu u => pu.scale ((vs.getD u []).getD (i * m.dv + j) 0)) p keys)
  let concat := heads.flatten
  return (List.range m.dModel).map fun o =>
    Interval.sum ((List.range (m.h * m.dv)).map fun r =>
      (concat.getD r (Interval.exact 0)).scale (m.wo o r))

/-- Encoder self-attention sees every position. -/
def unmasked (length : Nat) : Nat → List Nat := fun _ => List.range length

/-- Decoder self-attention masks out "illegal connections": position `t` sees
positions `0..t` only (Section 3.2.3). -/
def causal : Nat → List Nat := fun t => List.range (t + 1)

/-! ## The probe the training code runs -/

/-- Probe weights and inputs, defined identically in `train_ablation.py`
(`probe_weight`, `probe_input`). All are exactly representable in float32. -/
def probeWeight (salt row col : Nat) : Q := q ((((3 * row + 2 * col + salt) % 5 : Nat) : Int) - 2) 8
def probeInput (t c : Nat) : Q := q ((((2 * t + 3 * c) % 5 : Nat) : Int) - 2) 2

def probeLength : Nat := 3

def probe : MHA where
  dModel := 4
  h := 2
  dk := 4
  dv := 2
  sqrtDk := 2
  wq := probeWeight 1
  wk := probeWeight 2
  wv := probeWeight 3
  wo := probeWeight 4

theorem probe_sqrtDk : decide (probe.sqrtDk * probe.sqrtDk ≈ q probe.dk) = true := by decide

def probeX : List (List Q) := (List.range probeLength).map fun t => (List.range 4).map (probeInput t)

/-- Intervals containing the exact `MultiHead` output on the probe, for every
position `t` and channel `c`. -/
def probeReference (masked : Bool) : Option (List (List Interval)) :=
  (List.range probeLength).mapM fun t =>
    probe.output probeX (if masked then causal else unmasked probeLength) t

/-! ## Learning-rate schedule (Section 5.3) -/

/-- The square of `lrate = factor · d_model^-0.5 · min(n^-0.5, n · warmup^-1.5)` at
update `n` (counting from 1). The two branches are the two sides of the `min`:
for `n ≤ warmup` the linear warmup is smaller. Squaring keeps it rational. -/
def lrSquared (factor : Q) (dModel warmup n : Nat) : Q :=
  if n ≤ warmup then factor * factor * q (n * n) (dModel * warmup ^ 3)
  else factor * factor * q 1 (dModel * n)

end Spec
